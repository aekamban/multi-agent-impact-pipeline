"""
Agent 3 Test Suite (v3)
=====================================
Style: matches test_agent2.py -- realistic inputs, descriptive class names,
no mocking of domain logic, no LLM calls anywhere in this file.

Run with:
    python -m pytest test_agent3.py -v

New in v3:
  - Uses real project_state.ImpactMetrics and Track enum (no local duplicate)
  - Tests real ProjectState integration (update_impact_metrics path)
  - Tests StructuredIntake.model_dump() -> run_agent3() -> ImpactMetrics round-trip
  - sustained_action and equity_flag DB write tests (used by funder dashboard)
  - Extended metrics DB merge test (existing JSON preserved)
  - Partner narrative "count > names" test
  - Missing project ID raises ValueError
  - All DB tests use actual schema columns: carbon_lbs_estimated,
    carbon_calculation_json, carbon_target_met, people_reached,
    community_score_total, community_score_json, sustained_action, equity_flag
"""

import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass as py_dataclass

from project_state import (
    ImpactMetrics,
    ProjectState,
    StructuredIntake,
    CommunityPartner,
    RubricScores,
    Track,
    Phase,
    RawInput,
    TeacherContext,
    SchoolLocale,
    SchoolType,
    GradeBand,
)

from agent3 import (
    _coerce_bool,
    _safe_float,
    _safe_int,
    _intake_as_dict,
    _resolve_partnerships,
    _partner_narrative,
    _behavior_proxy_label,
    calculate_track_a,
    calculate_track_b,
    run_agent3,
    write_impact_to_db,
    write_impact_to_db_with_flags,
    EPA_ELECTRICITY_LBS_PER_KWH,
    EPA_NATURAL_GAS_LBS_PER_THERM,
    EPA_GASOLINE_LBS_PER_GALLON,
    EPA_DIESEL_LBS_PER_GALLON,
    EPA_CAR_LBS_PER_MILE,
    EPA_TREE_LBS_CO2_PER_YEAR,
    TRACK_A_TARGET_LBS,
    BEHAVIOR_CHANGE_SCORES,
    SUSTAINED_ACTION_BONUS,
)


# ─────────────────────────────────────────────────────────────────
# TEST HELPERS
# ─────────────────────────────────────────────────────────────────

class _FakeState:
    """Minimal plain-dict stand-in for ProjectState (for simple unit tests)."""
    def __init__(self, intake):
        self.structured_intake = intake
        self.impact_metrics = None
        self.reporting = {}  # Agent 3 must never touch this


class _PydanticLikeIntake:
    """Simulates a Pydantic v2 model with model_dump()."""
    def __init__(self, data: dict):
        self._data = data

    def model_dump(self):
        return self._data


@py_dataclass
class _DataclassIntake:
    """Simulates a plain dataclass structured_intake."""
    track: str = "B"
    project_type: str = "Composting program"
    num_students_max: int = 30
    community_partnerships_count: int = 0
    sustained_action: int = 0
    equity_flag: int = 0
    policy_influence_flag: int = 0


def _make_real_state_track_b() -> ProjectState:
    """Build a real ProjectState with StructuredIntake for Track B (Agriculture lab)."""
    state = ProjectState(
        raw_input=RawInput(
            raw_lab_name="agriculture lab",
            raw_project_description="Students measured compost rates.",
            raw_student_count_text="10-25",
        ),
        teacher_context=TeacherContext(
            school_name="Jefferson Montessori",
            subject_area="Environmental Science",
            country="US",
            school_locale=SchoolLocale.URBAN,
            school_type=SchoolType.MONTESSORI,
            title1_status="yes",
        )
    )
    state.structured_intake = StructuredIntake(
        canonical_lab_name="Agriculture and Climate Change",
        canonical_lab_id=2,
        lab_match_confidence=0.92,
        track=Track.B,
        num_students_min=10,
        num_students_max=25,
        num_students_estimate=18,
        num_students_display="10-25",
        thematic_topic="Food & Land Use",
        project_duration_weeks=6,
        project_type="Composting program",
        grade_band=GradeBand.ELEMENTARY,
        community_partnerships=[
            CommunityPartner(name="Local Food Bank", partner_type="NGO"),
            CommunityPartner(name="Cafeteria Staff", partner_type="school"),
        ],
        rubric_scores=RubricScores(reach=3.0, depth=4.0, equity=3.5, sustainability=4.0, fidelity=4.0),
        sustained_action=True,
        equity_flag=True,
    )
    state.phase = Phase.IMPLEMENTING
    return state


def _make_temp_db() -> str:
    """Create a minimal temp SQLite DB matching the real schema columns Agent 3 touches."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE learning_labs (
            id INTEGER PRIMARY KEY,
            lab_name TEXT,
            track TEXT,
            carbon_target_lbs REAL,
            thematic_topic TEXT,
            usage_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO learning_labs
            (id, lab_name, track, carbon_target_lbs, thematic_topic, usage_count)
        VALUES
            (1, 'Climate Impacts and Solutions with En-ROADS', 'A', 10000, 'Climate Solutions', 4),
            (2, 'Agriculture and Climate Change', 'B', NULL, 'Food & Land Use', 17);

        CREATE TABLE student_groups (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            group_name TEXT,
            num_students INTEGER,
            ability_level TEXT DEFAULT 'unknown',
            has_field_trip_access INTEGER DEFAULT 0,
            has_device_access INTEGER DEFAULT 1,
            special_interests TEXT,
            status TEXT DEFAULT 'planning',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO student_groups (id, session_id, group_name, num_students)
            VALUES (1, 1, 'Group A', 25);

        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            teacher_id INTEGER,
            lab_id INTEGER,
            classroom_code TEXT,
            academic_year TEXT,
            status TEXT DEFAULT 'planning',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO sessions (id, teacher_id, lab_id, classroom_code, academic_year, status)
            VALUES (1, 1, 1, 'ABC123', '2024-2025', 'implementing');

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            group_id INTEGER,
            session_id INTEGER,
            lab_id INTEGER,
            project_type_id INTEGER,
            track TEXT,
            project_title TEXT,
            project_description TEXT,
            thematic_topic TEXT,
            num_students_min INTEGER,
            num_students_max INTEGER,
            num_students_display TEXT,
            duration_weeks INTEGER,
            start_date DATE,
            end_date DATE,
            -- Track A fields
            carbon_lbs_estimated REAL,
            carbon_calculation_json TEXT,
            carbon_target_met INTEGER,
            -- Track B fields
            community_score_total REAL,
            community_score_json TEXT,
            people_reached INTEGER,
            people_reached_display TEXT,
            community_partnerships_json TEXT,
            community_partnerships_count INTEGER DEFAULT 0,
            -- Funder flags (used by database.py get_impact_summary aggregates)
            sustained_action INTEGER,
            equity_flag INTEGER,
            -- Other
            rubric_score_json TEXT,
            rubric_total REAL,
            student_quotes TEXT,
            highlights TEXT,
            media_urls TEXT,
            status TEXT DEFAULT 'planning',
            funder_summary_text TEXT,
            logic_model_json TEXT,
            map_export_json TEXT,
            followup_date DATE,
            followup_completed INTEGER DEFAULT 0,
            followup_notes TEXT,
            submission_source TEXT DEFAULT 'in_app',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    return path


def _insert_project(db_path: str, project_id: int, track: str,
                    existing_json: str = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO projects (id, group_id, session_id, lab_id, track, carbon_calculation_json)"
        " VALUES (?,1,1,1,?,?)",
        (project_id, track, existing_json)
    )
    conn.commit()
    conn.close()


def _read_project(db_path: str, project_id: int) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


# ─────────────────────────────────────────────────────────────────
# INPUT PARSING HELPERS
# ─────────────────────────────────────────────────────────────────

class TestCoerceBool(unittest.TestCase):
    def test_int_1_is_true(self):          self.assertTrue(_coerce_bool(1))
    def test_int_0_is_false(self):         self.assertFalse(_coerce_bool(0))
    def test_bool_true(self):              self.assertTrue(_coerce_bool(True))
    def test_bool_false(self):             self.assertFalse(_coerce_bool(False))
    def test_string_1(self):               self.assertTrue(_coerce_bool("1"))
    def test_string_0(self):               self.assertFalse(_coerce_bool("0"))
    def test_string_true_lower(self):      self.assertTrue(_coerce_bool("true"))
    def test_string_false_lower(self):     self.assertFalse(_coerce_bool("false"))
    def test_string_TRUE_upper(self):      self.assertTrue(_coerce_bool("TRUE"))
    def test_string_FALSE_upper(self):     self.assertFalse(_coerce_bool("FALSE"))
    def test_string_yes(self):             self.assertTrue(_coerce_bool("yes"))
    def test_string_no(self):              self.assertFalse(_coerce_bool("no"))
    def test_none_is_false(self):          self.assertFalse(_coerce_bool(None))
    def test_empty_string_is_false(self):  self.assertFalse(_coerce_bool(""))
    def test_unknown_string_is_false(self): self.assertFalse(_coerce_bool("maybe"))


class TestSafeFloat(unittest.TestCase):
    def test_plain_int(self):             self.assertEqual(_safe_float(500), 500.0)
    def test_plain_float(self):           self.assertAlmostEqual(_safe_float(10.5), 10.5)
    def test_string_integer(self):        self.assertEqual(_safe_float("10"), 10.0)
    def test_string_with_comma(self):     self.assertEqual(_safe_float("1,000"), 1000.0)
    def test_string_with_whitespace(self):self.assertEqual(_safe_float(" 500 "), 500.0)
    def test_none_returns_zero(self):     self.assertEqual(_safe_float(None), 0.0)
    def test_empty_string_zero(self):     self.assertEqual(_safe_float(""), 0.0)
    def test_invalid_string_zero(self):   self.assertEqual(_safe_float("about 100"), 0.0)
    def test_alpha_returns_zero(self):    self.assertEqual(_safe_float("lots"), 0.0)
    def test_zero_string(self):           self.assertEqual(_safe_float("0"), 0.0)


class TestSafeInt(unittest.TestCase):
    def test_comma_string(self):      self.assertEqual(_safe_int("1,500"), 1500)
    def test_invalid_returns_zero(self): self.assertEqual(_safe_int("n/a"), 0)
    def test_none_returns_zero(self): self.assertEqual(_safe_int(None), 0)


class TestIntakeAsDict(unittest.TestCase):
    def test_plain_dict_passthrough(self):
        d = {"track": "B", "num_students_max": 30}
        self.assertEqual(_intake_as_dict(d), d)

    def test_none_returns_empty_dict(self):
        self.assertEqual(_intake_as_dict(None), {})

    def test_pydantic_v2_model_dump(self):
        obj = _PydanticLikeIntake({"track": "A", "energy_kwh_reduced": 1000})
        result = _intake_as_dict(obj)
        self.assertEqual(result["track"], "A")

    def test_dataclass_via_dict(self):
        obj = _DataclassIntake(track="B", num_students_max=40)
        result = _intake_as_dict(obj)
        self.assertEqual(result["track"], "B")
        self.assertEqual(result["num_students_max"], 40)

    def test_real_structured_intake_model_dump(self):
        """Real StructuredIntake.model_dump() produces correctly typed fields."""
        si = StructuredIntake(
            track=Track.B,
            num_students_estimate=18,
            sustained_action=True,
            equity_flag=False,
            community_partnerships=[CommunityPartner(name="EcoKids", partner_type="NGO")],
        )
        d = _intake_as_dict(si)
        self.assertIsInstance(d["track"], Track)
        self.assertEqual(d["track"], Track.B)
        self.assertTrue(d["sustained_action"])
        self.assertFalse(d["equity_flag"])
        self.assertEqual(d["community_partnerships"][0]["name"], "EcoKids")


# ─────────────────────────────────────────────────────────────────
# PARTNERSHIP RESOLUTION AND NARRATIVE
# ─────────────────────────────────────────────────────────────────

class TestResolvePartnerships(unittest.TestCase):
    def test_explicit_count_only(self):
        count, names = _resolve_partnerships({"community_partnerships_count": 3})
        self.assertEqual(count, 3)
        self.assertEqual(names, [])

    def test_list_from_model_dump(self):
        """community_partnerships as list[dict] (model_dump output)."""
        partners = [{"name": "Riverside Recycling", "partner_type": "nonprofit", "description": ""},
                    {"name": "City Council", "partner_type": "government", "description": ""}]
        count, names = _resolve_partnerships({"community_partnerships": partners})
        self.assertEqual(count, 2)
        self.assertIn("Riverside Recycling", names)

    def test_json_string_derives_count_and_names(self):
        partners = [{"name": "EcoKids"}, {"name": "Green Schools"}]
        count, names = _resolve_partnerships({"community_partnerships_json": json.dumps(partners)})
        self.assertEqual(count, 2)
        self.assertIn("EcoKids", names)

    def test_explicit_count_wins_over_list_length(self):
        partners = [{"name": "A"}, {"name": "B"}]
        count, _ = _resolve_partnerships({"community_partnerships_count": 5,
                                          "community_partnerships": partners})
        self.assertEqual(count, 5)

    def test_count_derived_from_list_when_no_explicit(self):
        partners = [{"name": "X"}, {"name": "Y"}, {"name": "Z"}]
        count, _ = _resolve_partnerships({"community_partnerships_json": json.dumps(partners)})
        self.assertEqual(count, 3)

    def test_no_data_returns_zero(self):
        count, names = _resolve_partnerships({})
        self.assertEqual(count, 0)
        self.assertEqual(names, [])

    def test_malformed_json_returns_zero(self):
        count, _ = _resolve_partnerships({"community_partnerships_json": "not json {{{{"})
        self.assertEqual(count, 0)

    def test_real_community_partner_objects_via_model_dump(self):
        """CommunityPartner objects serialised by StructuredIntake.model_dump()."""
        si = StructuredIntake(
            community_partnerships=[
                CommunityPartner(name="Food Bank", partner_type="NGO"),
                CommunityPartner(name="City Hall", partner_type="government"),
            ]
        )
        d = si.model_dump()
        count, names = _resolve_partnerships(d)
        self.assertEqual(count, 2)
        self.assertIn("Food Bank", names)
        self.assertIn("City Hall", names)


class TestPartnerNarrative(unittest.TestCase):
    def test_zero_partners(self):
        self.assertIn("no community partners", _partner_narrative(0, []))

    def test_count_no_names(self):
        result = _partner_narrative(2, [])
        self.assertIn("2", result)
        self.assertIn("identified", result)

    def test_count_equals_names(self):
        result = _partner_narrative(2, ["Riverside Recycling", "City Council"])
        self.assertIn("partnering with", result)
        self.assertIn("Riverside Recycling", result)

    def test_count_greater_than_names(self):
        """Teacher knows of 5 partners; only 2 are named -- use 'including' phrasing."""
        result = _partner_narrative(5, ["Riverside Recycling", "City Council Office"])
        self.assertIn("5 community partners identified", result)
        self.assertIn("including", result)
        self.assertIn("Riverside Recycling", result)
        self.assertIn("City Council Office", result)

    def test_single_named_partner(self):
        result = _partner_narrative(1, ["EcoKids"])
        self.assertIn("partnering with EcoKids", result)


# ─────────────────────────────────────────────────────────────────
# TRACK A -- CO2 CALCULATIONS
# ─────────────────────────────────────────────────────────────────

class TestTrackAElectricitySavings(unittest.TestCase):
    def test_math_is_correct(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 1000})
        self.assertEqual(m.co2_reduction_lbs, round(1000 * EPA_ELECTRICITY_LBS_PER_KWH, 2))

    def test_impact_track_is_enum(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 500})
        self.assertEqual(m.impact_track, Track.A)

    def test_step_in_methodology_json(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 500})
        steps = json.loads(m.co2_reduction_methodology)["steps"]
        self.assertIn("Electricity savings", [s["step"] for s in steps])

    def test_epa_label_contains_step_name(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 500})
        self.assertIn("Electricity savings", m.epa_emissions_factor_used)

    def test_epa_label_is_str_not_none(self):
        m = calculate_track_a({"track": "A"})
        self.assertIsInstance(m.epa_emissions_factor_used, str)

    def test_comma_formatted_kwh_input(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": "1,000"})
        self.assertEqual(m.co2_reduction_lbs, round(1000 * EPA_ELECTRICITY_LBS_PER_KWH, 2))

    def test_invalid_kwh_treated_as_zero(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": "about a lot"})
        self.assertIsNone(m.co2_reduction_lbs)

    def test_co2_reduction_methodology_is_str_not_none(self):
        """co2_reduction_methodology is str in ImpactMetrics -- never None."""
        m = calculate_track_a({"track": "A"})
        self.assertIsInstance(m.co2_reduction_methodology, str)


class TestTrackANaturalGas(unittest.TestCase):
    def test_math(self):
        m = calculate_track_a({"track": "A", "natural_gas_therms": 100})
        self.assertEqual(m.co2_reduction_lbs, round(100 * EPA_NATURAL_GAS_LBS_PER_THERM, 2))


class TestTrackAGasoline(unittest.TestCase):
    def test_math(self):
        m = calculate_track_a({"track": "A", "gasoline_gallons": 50})
        self.assertEqual(m.co2_reduction_lbs, round(50 * EPA_GASOLINE_LBS_PER_GALLON, 2))


class TestTrackACarMiles(unittest.TestCase):
    def test_math(self):
        m = calculate_track_a({"track": "A", "car_miles_avoided": 1000})
        self.assertEqual(m.co2_reduction_lbs, round(1000 * EPA_CAR_LBS_PER_MILE, 2))


class TestTrackATreePlanting(unittest.TestCase):
    def test_math(self):
        m = calculate_track_a({"track": "A", "trees_planted": 10})
        self.assertEqual(m.co2_reduction_lbs, round(10 * EPA_TREE_LBS_CO2_PER_YEAR, 2))

    def test_comma_formatted_count(self):
        m = calculate_track_a({"track": "A", "trees_planted": "1,000"})
        self.assertEqual(m.co2_reduction_lbs, round(1000 * EPA_TREE_LBS_CO2_PER_YEAR, 2))


class TestTrackAMultipleFactors(unittest.TestCase):
    def test_combined_factors_add_up(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 5000, "trees_planted": 100})
        expected = round(5000 * EPA_ELECTRICITY_LBS_PER_KWH + 100 * EPA_TREE_LBS_CO2_PER_YEAR, 2)
        self.assertAlmostEqual(m.co2_reduction_lbs, expected, places=1)

    def test_two_factors_generate_two_steps(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 5000, "trees_planted": 100})
        steps = json.loads(m.co2_reduction_methodology)["steps"]
        self.assertEqual(len(steps), 2)


class TestTrackATargetMet(unittest.TestCase):
    def test_true_when_above_10000(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 12000})
        self.assertTrue(m.co2_target_met)

    def test_false_when_below_10000(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 100})
        self.assertFalse(m.co2_target_met)

    def test_none_when_no_inputs(self):
        m = calculate_track_a({"track": "A"})
        self.assertIsNone(m.co2_target_met)
        self.assertIsNone(m.co2_reduction_lbs)


class TestTrackATeacherOverride(unittest.TestCase):
    def test_override_accepted_when_no_factors(self):
        m = calculate_track_a({"track": "A", "carbon_lbs_estimated": 8500})
        self.assertEqual(m.co2_reduction_lbs, 8500.0)
        self.assertFalse(m.co2_target_met)

    def test_override_ignored_when_factors_present(self):
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 1000, "carbon_lbs_estimated": 99999})
        self.assertEqual(m.co2_reduction_lbs, round(1000 * EPA_ELECTRICITY_LBS_PER_KWH, 2))

    def test_comma_formatted_override(self):
        m = calculate_track_a({"track": "A", "carbon_lbs_estimated": "8,500"})
        self.assertEqual(m.co2_reduction_lbs, 8500.0)


# ─────────────────────────────────────────────────────────────────
# TRACK B -- COMMUNITY IMPACT METRICS
# ─────────────────────────────────────────────────────────────────

class TestTrackBImpactTrackIsEnum(unittest.TestCase):
    def test_impact_track_is_track_enum(self):
        m = calculate_track_b({"track": "B"})
        self.assertEqual(m.impact_track, Track.B)
        self.assertIsInstance(m.impact_track, Track)


class TestTrackBBehaviorChangeProxyIsStr(unittest.TestCase):
    """behavior_change_proxy is str in project_state.ImpactMetrics -- not int."""

    def test_behavior_change_proxy_is_str(self):
        m = calculate_track_b({"track": "B", "project_type": "Composting program"})
        self.assertIsInstance(m.behavior_change_proxy, str)

    def test_behavior_change_proxy_contains_project_type(self):
        m = calculate_track_b({"track": "B", "project_type": "Composting program"})
        self.assertIn("Composting program", m.behavior_change_proxy)

    def test_behavior_change_proxy_contains_score(self):
        m = calculate_track_b({"track": "B", "project_type": "Composting program"})
        self.assertIn("7/10", m.behavior_change_proxy)

    def test_sustained_bonus_reflected_in_label(self):
        m = calculate_track_b({"track": "B", "project_type": "Composting program", "sustained_action": 1})
        # Composting (7) + bonus (2) = 9, capped naturally; label should say 9
        self.assertIn("9/10", m.behavior_change_proxy)

    def test_renewable_energy_plus_sustained_caps_at_10(self):
        m = calculate_track_b({"track": "B", "project_type": "Renewable energy installation", "sustained_action": 1})
        self.assertIn("10/10", m.behavior_change_proxy)


class TestTrackBPeopleReached(unittest.TestCase):
    def test_explicit_people_reached(self):
        m = calculate_track_b({"track": "B", "people_reached": 300, "num_students_max": 25})
        self.assertEqual(m.reach_estimate, 300)

    def test_uses_num_students_estimate_over_max(self):
        m = calculate_track_b({"track": "B", "num_students_estimate": 75, "num_students_max": 120})
        self.assertEqual(m.reach_estimate, 75)

    def test_falls_back_to_num_students_max(self):
        m = calculate_track_b({"track": "B", "num_students_max": 120})
        self.assertEqual(m.reach_estimate, 120)

    def test_falls_back_to_num_students_min(self):
        m = calculate_track_b({"track": "B", "num_students_min": 30})
        self.assertEqual(m.reach_estimate, 30)

    def test_only_estimate_present(self):
        m = calculate_track_b({"track": "B", "num_students_estimate": 45})
        self.assertEqual(m.reach_estimate, 45)

    def test_reach_zero_when_no_student_data(self):
        m = calculate_track_b({"track": "B"})
        self.assertEqual(m.reach_estimate, 0)

    def test_comma_formatted_people_reached(self):
        m = calculate_track_b({"track": "B", "people_reached": "1,200"})
        self.assertEqual(m.reach_estimate, 1200)


class TestTrackBBooleanCoercion(unittest.TestCase):
    def test_sustained_action_string_true(self):
        m = calculate_track_b({"track": "B", "sustained_action": "true"})
        self.assertEqual(m.community_score_json["depth"], 25)

    def test_sustained_action_string_false(self):
        m = calculate_track_b({"track": "B", "sustained_action": "false"})
        self.assertEqual(m.community_score_json["depth"], 12)

    def test_sustained_action_string_0(self):
        m = calculate_track_b({"track": "B", "sustained_action": "0"})
        self.assertEqual(m.community_score_json["depth"], 12)

    def test_equity_flag_string_yes(self):
        m = calculate_track_b({"track": "B", "equity_flag": "yes"})
        self.assertEqual(m.community_score_json["equity"], 25)

    def test_equity_flag_string_no(self):
        m = calculate_track_b({"track": "B", "equity_flag": "no"})
        self.assertEqual(m.community_score_json["equity"], 10)

    def test_policy_flag_string_false(self):
        m = calculate_track_b({"track": "B", "policy_influence_flag": "false"})
        self.assertFalse(m.policy_influence_flag)

    def test_real_structured_intake_bool_fields(self):
        """Optional[bool] from StructuredIntake.model_dump() should pass through correctly."""
        si = StructuredIntake(track=Track.B, sustained_action=True, equity_flag=False)
        d = _intake_as_dict(si)
        m = calculate_track_b(d)
        self.assertEqual(m.community_score_json["depth"], 25)
        self.assertEqual(m.community_score_json["equity"], 10)


class TestTrackBCommunityScore(unittest.TestCase):
    def test_perfect_score_is_100(self):
        m = calculate_track_b({"track": "B", "people_reached": 600, "sustained_action": 1,
                               "equity_flag": 1, "community_partnerships_count": 3})
        self.assertEqual(m.community_score_total, 100.0)

    def test_total_equals_sum_of_dimensions(self):
        m = calculate_track_b({"track": "B", "people_reached": 600, "sustained_action": 1,
                               "equity_flag": 1, "community_partnerships_count": 3})
        s = m.community_score_json
        self.assertEqual(s["total"], s["reach"] + s["depth"] + s["equity"] + s["sustainability"])

    def test_minimal_intake_produces_valid_score(self):
        m = calculate_track_b({"track": "B"})
        self.assertGreater(m.community_score_total, 0)


class TestTrackBPolicyFields(unittest.TestCase):
    def test_policy_flag_true_when_set(self):
        m = calculate_track_b({"track": "B", "policy_influence_flag": 1,
                               "policy_description": "Students presented to city council."})
        self.assertTrue(m.policy_influence_flag)
        self.assertIsInstance(m.policy_influence_flag, bool)

    def test_policy_flag_default_false(self):
        m = calculate_track_b({"track": "B"})
        self.assertFalse(m.policy_influence_flag)

    def test_policy_description_empty_string_not_none(self):
        """policy_description is str in ImpactMetrics -- default '' not None."""
        m = calculate_track_b({"track": "B"})
        self.assertIsInstance(m.policy_description, str)

    def test_whitespace_only_policy_desc_becomes_empty(self):
        m = calculate_track_b({"track": "B", "policy_description": "   "})
        self.assertEqual(m.policy_description, "")


# ─────────────────────────────────────────────────────────────────
# RUN_AGENT3 STATE INTEGRATION
# ─────────────────────────────────────────────────────────────────

class TestRunAgent3WithRealProjectState(unittest.TestCase):
    """Integration tests using real ProjectState and StructuredIntake objects."""

    def test_real_state_track_b_agriculture(self):
        """Full round-trip: real ProjectState -> run_agent3 -> ImpactMetrics."""
        state = _make_real_state_track_b()
        run_agent3(state)
        m = state.impact_metrics
        self.assertIsInstance(m, ImpactMetrics)
        self.assertEqual(m.impact_track, Track.B)
        # num_students_estimate=18 should be the reach source
        self.assertEqual(m.reach_estimate, 18)
        # 2 CommunityPartner objects -> partnership_count=2
        self.assertEqual(m.partnership_count, 2)
        # sustained_action=True -> depth score 25; equity_flag=True -> equity score 25
        self.assertEqual(m.community_score_json["depth"], 25)
        self.assertEqual(m.community_score_json["equity"], 25)

    def test_real_state_uses_update_impact_metrics_helper(self):
        """run_agent3 calls state.update_impact_metrics() on real ProjectState."""
        state = _make_real_state_track_b()
        run_agent3(state)
        # If update_impact_metrics was called, timestamps.updated_at should have changed
        self.assertIsNotNone(state.timestamps.updated_at)

    def test_real_state_reporting_never_touched(self):
        state = _make_real_state_track_b()
        original_reporting = state.reporting.model_dump()
        run_agent3(state)
        self.assertEqual(state.reporting.model_dump(), original_reporting)

    def test_real_state_structured_intake_never_modified(self):
        state = _make_real_state_track_b()
        original_intake = state.structured_intake.model_dump()
        run_agent3(state)
        self.assertEqual(state.structured_intake.model_dump(), original_intake)

    def test_partner_names_from_real_community_partner_objects(self):
        """CommunityPartner objects from StructuredIntake appear in methodology notes."""
        state = _make_real_state_track_b()
        run_agent3(state)
        self.assertIn("Local Food Bank", state.impact_metrics.methodology_notes)


class TestRunAgent3FakeState(unittest.TestCase):
    def test_plain_dict_track_a(self):
        state = _FakeState({"track": "A", "energy_kwh_reduced": 5000})
        run_agent3(state)
        self.assertEqual(state.impact_metrics.impact_track, Track.A)

    def test_plain_dict_track_b(self):
        state = _FakeState({"track": "B", "project_type": "Composting program", "num_students_max": 30})
        run_agent3(state)
        self.assertEqual(state.impact_metrics.impact_track, Track.B)

    def test_track_enum_value_in_dict(self):
        """Track enum coming through model_dump() is handled correctly."""
        state = _FakeState({"track": Track.B, "num_students_max": 25})
        run_agent3(state)
        self.assertEqual(state.impact_metrics.impact_track, Track.B)

    def test_defaults_to_track_b_when_track_missing(self):
        state = _FakeState({})
        run_agent3(state)
        self.assertEqual(state.impact_metrics.impact_track, Track.B)

    def test_handles_none_structured_intake(self):
        state = _FakeState({})
        state.structured_intake = None
        run_agent3(state)
        self.assertIsInstance(state.impact_metrics, ImpactMetrics)

    def test_reporting_never_touched(self):
        state = _FakeState({"track": "B", "num_students_max": 25})
        state.reporting = {"sentinel": "untouched"}
        run_agent3(state)
        self.assertEqual(state.reporting, {"sentinel": "untouched"})

    def test_structured_intake_never_modified(self):
        intake = {"track": "A", "energy_kwh_reduced": 1000}
        original = dict(intake)
        state = _FakeState(intake)
        run_agent3(state)
        self.assertEqual(state.structured_intake, original)


# ─────────────────────────────────────────────────────────────────
# DB WRITE INTEGRATION
# ─────────────────────────────────────────────────────────────────

class TestWriteImpactToDb(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_temp_db()
        _insert_project(self.db_path, 1, "A")
        _insert_project(self.db_path, 2, "B")

    def tearDown(self):
        os.unlink(self.db_path)

    # ── Track A ───────────────────────────────────────────────────

    def test_track_a_writes_carbon_lbs_estimated(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_lbs=9500.0,
                          co2_reduction_methodology='{"steps":[]}', co2_target_met=False)
        write_impact_to_db(1, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 1)["carbon_lbs_estimated"], 9500.0)

    def test_track_a_writes_carbon_calculation_json(self):
        payload = json.dumps({"steps": [{"step": "Electricity savings", "result_lbs": 851.0}]})
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_lbs=851.0,
                          co2_reduction_methodology=payload, co2_target_met=False)
        write_impact_to_db(1, m, db_path=self.db_path)
        stored = json.loads(_read_project(self.db_path, 1)["carbon_calculation_json"])
        self.assertEqual(stored["steps"][0]["step"], "Electricity savings")

    def test_track_a_writes_carbon_target_met_as_int(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_lbs=11000.0,
                          co2_reduction_methodology='{}', co2_target_met=True)
        write_impact_to_db(1, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 1)["carbon_target_met"], 1)

    def test_track_a_target_met_false_writes_zero(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_lbs=5000.0,
                          co2_reduction_methodology='{}', co2_target_met=False)
        write_impact_to_db(1, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 1)["carbon_target_met"], 0)

    def test_track_a_target_met_none_writes_null(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_methodology='{}')
        write_impact_to_db(1, m, db_path=self.db_path)
        self.assertIsNone(_read_project(self.db_path, 1)["carbon_target_met"])

    # ── Track A sustained_action and equity_flag ──────────────────

    def test_track_a_sustained_action_written_with_flags(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_methodology='{}')
        write_impact_to_db_with_flags(1, m, sustained_action=True, equity_flag=False,
                                      db_path=self.db_path)
        row = _read_project(self.db_path, 1)
        self.assertEqual(row["sustained_action"], 1)
        self.assertEqual(row["equity_flag"], 0)

    def test_track_a_none_flags_do_not_overwrite_existing(self):
        """COALESCE: None flag leaves existing DB value untouched."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE projects SET sustained_action=1, equity_flag=1 WHERE id=1")
        conn.commit()
        conn.close()
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_methodology='{}')
        write_impact_to_db_with_flags(1, m, sustained_action=None, equity_flag=None,
                                      db_path=self.db_path)
        row = _read_project(self.db_path, 1)
        self.assertEqual(row["sustained_action"], 1)
        self.assertEqual(row["equity_flag"], 1)

    # ── Track B ───────────────────────────────────────────────────

    def test_track_b_writes_people_reached(self):
        m = ImpactMetrics(impact_track=Track.B, reach_estimate=250, partnership_count=2,
                          community_score_total=72.0,
                          community_score_json={"reach":20,"depth":25,"equity":10,"sustainability":17,"total":72})
        write_impact_to_db(2, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 2)["people_reached"], 250)

    def test_track_b_writes_community_score_total(self):
        m = ImpactMetrics(impact_track=Track.B, reach_estimate=100, community_score_total=65.0,
                          community_score_json={"reach":15,"depth":12,"equity":10,"sustainability":28,"total":65},
                          partnership_count=1)
        write_impact_to_db(2, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 2)["community_score_total"], 65.0)

    def test_track_b_community_score_json_round_trips(self):
        score = {"reach":25,"depth":25,"equity":25,"sustainability":25,"total":100}
        m = ImpactMetrics(impact_track=Track.B, community_score_total=100.0,
                          community_score_json=score, partnership_count=3)
        write_impact_to_db(2, m, db_path=self.db_path)
        stored = json.loads(_read_project(self.db_path, 2)["community_score_json"])
        self.assertEqual(stored["total"], 100)

    def test_track_b_writes_partnership_count(self):
        m = ImpactMetrics(impact_track=Track.B, partnership_count=4, community_score_total=80.0,
                          community_score_json={"reach":20,"depth":25,"equity":10,"sustainability":25,"total":80})
        write_impact_to_db(2, m, db_path=self.db_path)
        self.assertEqual(_read_project(self.db_path, 2)["community_partnerships_count"], 4)

    def test_track_b_sustained_action_and_equity_flag_written(self):
        m = ImpactMetrics(impact_track=Track.B, community_score_total=80.0,
                          community_score_json={"reach":20,"depth":25,"equity":25,"sustainability":10,"total":80},
                          partnership_count=1)
        write_impact_to_db_with_flags(2, m, sustained_action=True, equity_flag=True,
                                      db_path=self.db_path)
        row = _read_project(self.db_path, 2)
        self.assertEqual(row["sustained_action"], 1)
        self.assertEqual(row["equity_flag"], 1)

    def test_track_b_equity_flag_false_writes_zero(self):
        m = ImpactMetrics(impact_track=Track.B, community_score_total=60.0,
                          community_score_json={"reach":15,"depth":12,"equity":10,"sustainability":23,"total":60},
                          partnership_count=0)
        write_impact_to_db_with_flags(2, m, sustained_action=False, equity_flag=False,
                                      db_path=self.db_path)
        row = _read_project(self.db_path, 2)
        self.assertEqual(row["sustained_action"], 0)
        self.assertEqual(row["equity_flag"], 0)

    def test_track_b_extended_metrics_in_carbon_calculation_json(self):
        """behavior_change_proxy, awareness_scale, etc. survive round-trip."""
        m = ImpactMetrics(
            impact_track=Track.B,
            reach_estimate=100,
            behavior_change_proxy="Composting program -- score 7/10 (High)",
            awareness_scale="High -- measurable, lasting behavior change expected",
            partnership_count=1,
            policy_influence_flag=True,
            policy_description="Resolution passed.",
            community_score_total=65.0,
            community_score_json={"reach":15,"depth":25,"equity":10,"sustainability":15,"total":65},
            methodology_notes="Full methodology notes.",
        )
        write_impact_to_db(2, m, db_path=self.db_path)
        row = _read_project(self.db_path, 2)
        ext = json.loads(row["carbon_calculation_json"])["extended_metrics"]
        self.assertIn("Composting program", ext["behavior_change_proxy"])
        self.assertIn("High", ext["awareness_scale"])
        self.assertTrue(ext["policy_influence_flag"])
        self.assertIn("Resolution", ext["policy_description"])

    def test_track_b_existing_json_is_merged_not_overwritten(self):
        """If carbon_calculation_json already has content, extended_metrics is merged in."""
        existing = json.dumps({"some_prior_key": "some_prior_value"})
        _insert_project(self.db_path, 3, "B", existing_json=existing)

        m = ImpactMetrics(
            impact_track=Track.B,
            behavior_change_proxy="Test -- score 5/10 (Medium)",
            community_score_total=50.0,
            community_score_json={"reach":10,"depth":12,"equity":10,"sustainability":18,"total":50},
        )
        write_impact_to_db(3, m, db_path=self.db_path)
        row = _read_project(self.db_path, 3)
        stored = json.loads(row["carbon_calculation_json"])
        # Original key preserved
        self.assertEqual(stored["some_prior_key"], "some_prior_value")
        # New extended_metrics added
        self.assertIn("extended_metrics", stored)

    def test_track_b_none_flags_do_not_overwrite_existing(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE projects SET sustained_action=1, equity_flag=1 WHERE id=2")
        conn.commit()
        conn.close()
        m = ImpactMetrics(impact_track=Track.B, community_score_total=60.0,
                          community_score_json={"reach":15,"depth":12,"equity":10,"sustainability":23,"total":60})
        write_impact_to_db_with_flags(2, m, sustained_action=None, equity_flag=None,
                                      db_path=self.db_path)
        row = _read_project(self.db_path, 2)
        self.assertEqual(row["sustained_action"], 1)
        self.assertEqual(row["equity_flag"], 1)

    def test_missing_project_id_raises_value_error(self):
        m = ImpactMetrics(impact_track=Track.A, co2_reduction_methodology='{}')
        with self.assertRaises(ValueError) as ctx:
            write_impact_to_db(999, m, db_path=self.db_path)
        self.assertIn("999", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────
# REALISTIC SUBMISSION SCENARIOS
# ─────────────────────────────────────────────────────────────────

class TestRealisticSubmissions(unittest.TestCase):
    def test_agriculture_lab_minimal_via_real_state(self):
        """Most common lab (17/46). Minimal teacher info via real ProjectState."""
        state = _make_real_state_track_b()
        run_agent3(state)
        m = state.impact_metrics
        self.assertEqual(m.impact_track, Track.B)
        self.assertGreater(m.community_score_total, 0)
        self.assertIsInstance(m.behavior_change_proxy, str)

    def test_civics_lab_policy_outcome(self):
        """Civics Climate Action (12/46). Policy outcome is primary metric."""
        m = calculate_track_b({
            "track": "B", "project_type": "Policy advocacy / letter writing",
            "people_reached": 500, "community_partnerships_count": 2,
            "sustained_action": 0, "equity_flag": 1,
            "policy_influence_flag": 1,
            "policy_description": "Students lobbied for and won a district sustainability policy.",
        })
        self.assertTrue(m.policy_influence_flag)
        self.assertIn("Students lobbied", m.policy_description)
        self.assertEqual(m.community_score_json["equity"], 25)

    def test_enroads_project_meets_target(self):
        """En-ROADS (4/46). Electricity + trees -> meets 10,000 lb target."""
        m = calculate_track_a({"track": "A", "energy_kwh_reduced": 8000, "trees_planted": 70})
        self.assertTrue(m.co2_target_met)
        self.assertGreater(m.co2_reduction_lbs, 10000)
        self.assertEqual(m.impact_track, Track.A)

    def test_renewable_energy_high_behavior_change(self):
        m = calculate_track_b({
            "track": "B", "project_type": "Renewable energy installation",
            "people_reached": 200, "sustained_action": 1, "community_partnerships_count": 1,
        })
        self.assertIn("10/10", m.behavior_change_proxy)
        self.assertIn("High", m.awareness_scale)


# ─────────────────────────────────────────────────────────────────
# EPA CONSTANTS SANITY CHECKS
# ─────────────────────────────────────────────────────────────────

class TestEpaConstantsSanity(unittest.TestCase):
    def test_electricity(self):  self.assertAlmostEqual(EPA_ELECTRICITY_LBS_PER_KWH, 0.851, places=3)
    def test_natural_gas(self):  self.assertAlmostEqual(EPA_NATURAL_GAS_LBS_PER_THERM, 11.7, places=1)
    def test_gasoline(self):     self.assertAlmostEqual(EPA_GASOLINE_LBS_PER_GALLON, 19.6, places=1)
    def test_diesel(self):       self.assertAlmostEqual(EPA_DIESEL_LBS_PER_GALLON, 22.4, places=1)
    def test_car_miles(self):    self.assertAlmostEqual(EPA_CAR_LBS_PER_MILE, 0.891, places=3)
    def test_trees(self):        self.assertAlmostEqual(EPA_TREE_LBS_CO2_PER_YEAR, 48.0, places=1)
    def test_target(self):       self.assertEqual(TRACK_A_TARGET_LBS, 10_000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

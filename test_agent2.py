"""
test_agent2.py
TCImpact — Agent 2 Test Suite

Tests use realistic messy inputs drawn from real TCI Jotform submission patterns.

Test gating:
    - All pure-Python tests run always (no env vars needed)
    - LLM-dependent tests require: LIVE_LLM=1
      e.g.  LIVE_LLM=1 python -m pytest test_agent2.py -v

Run all non-LLM tests:
    python -m pytest test_agent2.py -v

Run everything including LLM:
    LIVE_LLM=1 python -m pytest test_agent2.py -v
"""

import os
import pytest

from agent2 import (
    assign_track,
    extract_partners,
    infer_equity_flag,
    infer_project_type,
    infer_sustained_action,
    _is_title1,
    match_lab_name,
    normalize_student_count,
    process_submission,
    LOW_CONFIDENCE_THRESHOLD,
)
from project_state import (
    Phase,
    RawInput,
    TeacherContext,
    GradeBand,
    Track,
    SchoolLocale,
    SchoolType,
)

LIVE_LLM = os.getenv("LIVE_LLM", "0") == "1"
skip_no_llm = pytest.mark.skipif(not LIVE_LLM, reason="Requires LIVE_LLM=1")


# ═════════════════════════════════════════
# 1. LAB NAME MATCHING
# ═════════════════════════════════════════

class TestMatchLabName:

    # ── Exact / near-exact canonical names ──────────────────────────

    def test_exact_canonical_agriculture(self):
        name, lab_id, conf = match_lab_name("Agriculture and Climate Change")
        assert name == "Agriculture and Climate Change"
        assert lab_id == 2
        assert conf >= 0.95

    def test_exact_canonical_enroads(self):
        name, lab_id, conf = match_lab_name("Climate Impacts and Solutions with En-ROADS")
        assert name == "Climate Impacts and Solutions with En-ROADS"
        assert lab_id == 1
        assert conf >= 0.95

    # ── Informal names from real submissions ────────────────────────

    def test_informal_agriculture_lowercase(self):
        name, _, conf = match_lab_name("agriculture lab")
        assert name == "Agriculture and Climate Change"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_agriculture_short(self):
        name, _, conf = match_lab_name("the agriculture one")
        assert name == "Agriculture and Climate Change"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_enroads_hyphen_variant(self):
        name, lab_id, conf = match_lab_name("en-roads")
        assert name == "Climate Impacts and Solutions with En-ROADS"
        assert lab_id == 1
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_enroads_no_hyphen(self):
        name, _, conf = match_lab_name("enroads simulation")
        assert name == "Climate Impacts and Solutions with En-ROADS"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_civics(self):
        name, _, conf = match_lab_name("civics and climate")
        assert name == "Civics Climate Action"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_renewable(self):
        name, _, conf = match_lab_name("renewable energy lab")
        assert name == "Renewable Energy"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_sea_level(self):
        name, _, conf = match_lab_name("sea level rise lab")
        assert name == "Sea Level Rise"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_floods(self):
        name, _, conf = match_lab_name("the flood one")
        assert name == "Floods and Droughts"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_wildfires(self):
        name, _, conf = match_lab_name("wildfire unit")
        assert name == "Wildfires"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_justice(self):
        name, _, conf = match_lab_name("climate justice lab")
        assert name == "Climate Justice and Equity"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_health(self):
        name, _, conf = match_lab_name("climate and health")
        assert name == "Climate Change and Health"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_migration(self):
        name, _, conf = match_lab_name("climate migration unit")
        assert name == "Climate Migration"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    def test_informal_invasive(self):
        name, _, conf = match_lab_name("invasive species project")
        assert name == "Invasive Species"
        assert conf >= LOW_CONFIDENCE_THRESHOLD

    # ── Low-confidence cases ─────────────────────────────────────────

    def test_vague_input_returns_low_confidence(self):
        _, _, conf = match_lab_name("the science one")
        assert conf < LOW_CONFIDENCE_THRESHOLD

    def test_empty_input_returns_empty(self):
        name, lab_id, conf = match_lab_name("")
        assert name == ""
        assert lab_id == 0
        assert conf == 0.0

    def test_gibberish_returns_low_confidence(self):
        _, _, conf = match_lab_name("xyzzy foobar baz")
        assert conf < LOW_CONFIDENCE_THRESHOLD

    # ── Lab ID correctness ───────────────────────────────────────────

    def test_lab_ids_are_correct_for_all_canonical(self):
        expected = {
            "Climate Impacts and Solutions with En-ROADS": 1,
            "Agriculture and Climate Change": 2,
            "Civics Climate Action": 3,
            "Climate Justice and Equity": 4,
            "Renewable Energy": 5,
            "Wildfires": 6,
            "Floods and Droughts": 7,
            "Sea Level Rise": 8,
            "Invasive Species": 9,
            "Climate Change and Health": 10,
            "Climate Migration": 11,
        }
        for lab_name, expected_id in expected.items():
            _, lab_id, _ = match_lab_name(lab_name)
            assert lab_id == expected_id, f"Wrong ID for {lab_name}: got {lab_id}"


    def test_none_input_returns_empty(self):
        """match_lab_name(None) must not raise — returns empty tuple."""
        name, lab_id, conf = match_lab_name(None)
        assert name == ""
        assert lab_id == 0
        assert conf == 0.0

    def test_whitespace_only_returns_empty(self):
        name, lab_id, conf = match_lab_name("   ")
        assert name == "" and lab_id == 0 and conf == 0.0


# ═════════════════════════════════════════
# 2. STUDENT COUNT NORMALIZATION
# ═════════════════════════════════════════

class TestNormalizeStudentCount:

    def test_plain_integer(self):
        lo, hi, est = normalize_student_count("30")
        assert lo == 30 and hi == 30 and est == 30

    def test_integer_with_word(self):
        lo, hi, est = normalize_student_count("25 students")
        assert lo == 25 and hi == 25 and est == 25

    def test_range_hyphen(self):
        lo, hi, est = normalize_student_count("10-25")
        assert lo == 10 and hi == 25 and est == 17

    def test_range_with_grade_band(self):
        """Real submission format: "10-25, K-8th" — grade band must not corrupt range."""
        lo, hi, est = normalize_student_count("10-25, K-8th")
        assert lo == 10 and hi == 25
        assert est == 17

    def test_range_to_word(self):
        lo, hi, est = normalize_student_count("15 to 30")
        assert lo == 15 and hi == 30

    def test_plus_suffix(self):
        lo, hi, est = normalize_student_count("500+")
        assert lo == 500
        assert hi is None
        assert est == 500

    def test_about_prefix(self):
        lo, hi, est = normalize_student_count("about 30")
        assert lo is None and hi is None and est == 30

    def test_around_prefix(self):
        lo, hi, est = normalize_student_count("around 100")
        assert est == 100

    def test_approximately(self):
        lo, hi, est = normalize_student_count("approximately 50")
        assert est == 50

    def test_tilde_prefix(self):
        lo, hi, est = normalize_student_count("~45")
        assert est == 45

    def test_empty_string(self):
        lo, hi, est = normalize_student_count("")
        assert lo is None and hi is None and est is None

    def test_grade_only_no_number(self):
        lo, hi, est = normalize_student_count("K-8th")
        assert lo is None and hi is None and est is None

    def test_qualitative_no_number(self):
        lo, hi, est = normalize_student_count("many students")
        assert lo is None and hi is None and est is None

    def test_large_range(self):
        lo, hi, est = normalize_student_count("200-400")
        assert lo == 200 and hi == 400 and est == 300

    def test_reversed_range_is_corrected(self):
        """Should normalize even if teacher writes high-low."""
        lo, hi, est = normalize_student_count("25-10")
        assert lo == 10 and hi == 25

    def test_real_submission_complex(self):
        """Simulates a realistic messy real-world submission."""
        lo, hi, est = normalize_student_count("10-25, K-8th grade")
        assert lo == 10
        assert hi == 25


    def test_k12_grade_only(self):
        """Pure grade range with no student number should return all None."""
        lo, hi, est = normalize_student_count("K-12")
        assert lo is None and hi is None and est is None

    def test_approx_with_parentheses(self):
        """'two classes (~60)' — tilde+number inside parens should parse."""
        lo, hi, est = normalize_student_count("two classes (~60)")
        assert est == 60
        assert lo is None and hi is None

    def test_about_with_trailing_context(self):
        """'about 30 students across 2 classes' — should extract 30, not 2."""
        lo, hi, est = normalize_student_count("about 30 students across 2 classes")
        assert est == 30


    def test_bare_grade_range_9_12(self):
        """9-12 alone is almost always a grade range, not a student count."""
        lo, hi, est = normalize_student_count("9-12")
        assert lo is None and hi is None and est is None

    def test_bare_grade_range_6_8(self):
        lo, hi, est = normalize_student_count("6-8")
        assert lo is None and hi is None and est is None

    def test_explicit_grades_prefix(self):
        """'grades 9-12' — explicit grade word makes intent unambiguous."""
        lo, hi, est = normalize_student_count("grades 9-12")
        assert lo is None and hi is None and est is None

    def test_classes_of_students_prefers_student_count(self):
        """'2 classes of 30 students' — should return 30, not 2."""
        lo, hi, est = normalize_student_count("2 classes of 30 students")
        assert est == 30
        assert lo is None and hi is None

    def test_sections_students_total(self):
        """'3 sections, 90 students total' — should return 90."""
        lo, hi, est = normalize_student_count("3 sections, 90 students total")
        assert est == 90

    def test_groups_students(self):
        """'6 groups, 24 students' — should return 24."""
        lo, hi, est = normalize_student_count("6 groups, 24 students")
        assert est == 24


# ═════════════════════════════════════════
# 3. TRACK ASSIGNMENT
# ═════════════════════════════════════════

class TestAssignTrack:

    def test_enroads_is_track_a(self):
        assert assign_track("Climate Impacts and Solutions with En-ROADS") == Track.A

    def test_agriculture_is_track_b(self):
        assert assign_track("Agriculture and Climate Change") == Track.B

    def test_civics_is_track_b(self):
        assert assign_track("Civics Climate Action") == Track.B

    def test_all_non_enroads_are_track_b(self):
        track_b_labs = [
            "Agriculture and Climate Change",
            "Civics Climate Action",
            "Climate Justice and Equity",
            "Renewable Energy",
            "Wildfires",
            "Floods and Droughts",
            "Sea Level Rise",
            "Invasive Species",
            "Climate Change and Health",
            "Climate Migration",
        ]
        for lab in track_b_labs:
            assert assign_track(lab) == Track.B, f"Expected Track B for {lab}"

    def test_empty_string_returns_none(self):
        assert assign_track("") is None

    def test_unrecognized_name_returns_track_b(self):
        # Unknown labs default to Track B (safe fallback)
        assert assign_track("Unknown Lab Name") == Track.B


# ═════════════════════════════════════════
# 4. COMMUNITY PARTNER EXTRACTION (heuristic)
# ═════════════════════════════════════════

class TestExtractPartnersHeuristic:
    """All tests in this class run without LIVE_LLM — uses regex heuristic."""

    def test_partnered_with_single(self):
        partners = extract_partners("We partnered with the local food bank.")
        names = [p.name for p in partners]
        assert any("food bank" in n.lower() for n in names)

    def test_collaborated_with(self):
        partners = extract_partners("Students collaborated with Norwalk Parks Department.")
        names = [p.name for p in partners]
        assert any("norwalk" in n.lower() or "parks" in n.lower() for n in names)

    def test_worked_with_multiple(self):
        partners = extract_partners(
            "We worked with the city council and a local nonprofit."
        )
        assert len(partners) >= 1

    def test_supported_by(self):
        partners = extract_partners("This project was supported by the EPA.")
        names = [p.name.lower() for p in partners]
        assert any("epa" in n for n in names)

    def test_no_partners_mentioned(self):
        partners = extract_partners("Students conducted a composting experiment in class.")
        assert isinstance(partners, list)

    def test_empty_narrative(self):
        assert extract_partners("") == []
        assert extract_partners("   ") == []

    def test_partner_type_government(self):
        partners = extract_partners("Partnered with the city of Norwalk.")
        types = [p.partner_type for p in partners]
        assert any(t == "government" for t in types)

    def test_partner_type_school_internal(self):
        """Internal school staff should still be extracted if mentioned as collaborator."""
        partners = extract_partners("Worked with cafeteria staff and the school principal.")
        assert len(partners) >= 1

    def test_deduplication(self):
        """Same partner mentioned twice should not create duplicates."""
        partners = extract_partners(
            "Partnered with Green Alliance. We worked with Green Alliance for materials."
        )
        names_lower = [p.name.lower() for p in partners]
        assert names_lower.count("green alliance") <= 1

    def test_real_submission_narrative(self):
        """Simulates a realistic multi-partner narrative from a TCI submission."""
        narrative = (
            "Our students partnered with Harvest Hands Community Farm and the "
            "Norwalk Public Library. We also collaborated with a local nonprofit "
            "called GreenRoots and received support from the city's sustainability office."
        )
        partners = extract_partners(narrative)
        assert len(partners) >= 2


    def test_partner_in_description_not_partner_field(self):
        """
        Partners mentioned only in project description (not partner field)
        must still be extracted when process_submission combines both fields.
        """
        from project_state import RawInput
        from agent2 import process_submission
        raw = RawInput(
            raw_lab_name="agriculture lab",
            raw_project_description="Students worked with Harvest Hands Community Farm on a composting pilot.",
            raw_student_count_text="20",
            raw_community_partners="",   # intentionally empty
        )
        state = process_submission(raw)
        names = [p.name.lower() for p in state.structured_intake.community_partnerships]
        assert any("harvest hands" in n for n in names), f"Expected Harvest Hands in {names}"


    def test_org_name_with_and_not_split(self):
        """'Boys and Girls Club' must not be split into 'Boys' and 'Girls Club'."""
        partners = extract_partners("Worked with Boys and Girls Club of Norwalk.")
        names = [p.name for p in partners]
        assert any("Boys and Girls Club" in n for n in names), f"Expected intact name, got {names}"
        # Must NOT have produced a bare "Boys" entry
        assert not any(n.strip().lower() == "boys" for n in names)

    def test_dept_name_with_and_not_split(self):
        """Multi-word dept names like 'Department of Energy and Environment' stay intact."""
        partners = extract_partners("Partnered with Department of Energy and Environment.")
        names = [p.name for p in partners]
        assert any("Energy and Environment" in n or "Department of Energy" in n for n in names),             f"Expected intact dept name, got {names}"


# ═════════════════════════════════════════
# 5. LLM PARTNER EXTRACTION (gated)
# ═════════════════════════════════════════

class TestExtractPartnersLLM:

    @skip_no_llm
    def test_llm_extracts_named_organizations(self):
        narrative = (
            "Our class partnered with the Audubon Society and Yale School of the Environment. "
            "We also worked with the Norwalk Mayor's office on a policy brief."
        )
        partners = extract_partners(narrative)
        names_lower = [p.name.lower() for p in partners]
        assert any("audubon" in n for n in names_lower)
        assert any("yale" in n for n in names_lower)

    @skip_no_llm
    def test_llm_returns_list_on_no_partners(self):
        partners = extract_partners("Students completed a poster project in class.")
        assert isinstance(partners, list)

    @skip_no_llm
    def test_llm_partner_types_are_valid(self):
        valid_types = {"government", "university", "NGO", "business", "school", "community", "media"}
        narrative = "Worked with the city council, a university research lab, and a local NGO."
        partners = extract_partners(narrative)
        for p in partners:
            assert p.partner_type in valid_types, f"Invalid partner_type: {p.partner_type}"


# ═════════════════════════════════════════
# 6. PROCESS_SUBMISSION — INTEGRATION
# ═════════════════════════════════════════

class TestProcessSubmission:

    def _make_raw(self, **kwargs) -> RawInput:
        defaults = dict(
            raw_lab_name="agriculture lab",
            raw_project_description="Students measured compost rates.",
            raw_student_count_text="10-25, K-8th",
            raw_community_partners="Partnered with Harvest Hands Community Farm.",
            raw_location="Norwalk, CT",
        )
        defaults.update(kwargs)
        return RawInput(**defaults)

    def test_returns_project_state(self):
        from project_state import ProjectState
        state = process_submission(self._make_raw())
        assert isinstance(state, ProjectState)

    def test_structured_intake_populated(self):
        state = process_submission(self._make_raw())
        si = state.structured_intake
        assert si.canonical_lab_name == "Agriculture and Climate Change"
        assert si.track == Track.B
        assert si.num_students_estimate is not None

    def test_student_count_normalized(self):
        state = process_submission(self._make_raw(raw_student_count_text="10-25, K-8th"))
        si = state.structured_intake
        assert si.num_students_min == 10
        assert si.num_students_max == 25
        assert si.num_students_display == "10-25, K-8th"

    def test_original_display_preserved(self):
        raw_text = "about 30 students"
        state = process_submission(self._make_raw(raw_student_count_text=raw_text))
        assert state.structured_intake.num_students_display == raw_text

    def test_enroads_assigned_track_a(self):
        state = process_submission(self._make_raw(raw_lab_name="en-roads"))
        assert state.structured_intake.track == Track.A

    def test_partners_extracted(self):
        state = process_submission(self._make_raw(
            raw_community_partners="Partnered with Harvest Hands Community Farm."
        ))
        assert len(state.structured_intake.community_partnerships) >= 1

    def test_no_partners_gives_empty_list(self):
        state = process_submission(self._make_raw(raw_community_partners=""))
        assert state.structured_intake.community_partnerships == []

    def test_low_confidence_adds_warning(self):
        state = process_submission(self._make_raw(raw_lab_name="the science thing"))
        assert len(state.warnings) > 0
        assert any("confidence" in w.lower() or "match" in w.lower() for w in state.warnings)

    def test_unparseable_count_adds_warning(self):
        state = process_submission(self._make_raw(raw_student_count_text="lots"))
        assert any("student" in w.lower() or "count" in w.lower() or "parse" in w.lower()
                   for w in state.warnings)

    def test_phase_is_planning(self):
        state = process_submission(self._make_raw())
        assert state.phase == Phase.PLANNING

    def test_timestamps_set(self):
        state = process_submission(self._make_raw())
        assert state.timestamps.intake_completed_at is not None
        assert state.timestamps.updated_at is not None

    def test_teacher_context_passed_through(self):
        ctx = TeacherContext(
            school_name="Jefferson Montessori",
            city="Norwalk",
            state_province="CT",
            country="US",
            school_locale=SchoolLocale.URBAN,
            school_type=SchoolType.MONTESSORI,
        )
        state = process_submission(self._make_raw(), teacher_context=ctx)
        assert state.teacher_context.school_name == "Jefferson Montessori"
        assert state.teacher_context.country == "US"

    def test_impact_metrics_untouched(self):
        """Agent 2 must never write to impact_metrics."""
        state = process_submission(self._make_raw())
        im = state.impact_metrics
        assert im.co2_reduction_lbs is None
        assert im.reach_estimate is None
        assert im.impact_track is None

    def test_reporting_untouched(self):
        """Agent 2 must never write to reporting."""
        state = process_submission(self._make_raw())
        rp = state.reporting
        assert rp.funder_summary == ""
        assert rp.jotform_draft == {}

    def test_thematic_topic_populated_from_registry(self):
        state = process_submission(self._make_raw(raw_lab_name="agriculture lab"))
        assert state.structured_intake.thematic_topic == "Food & Land Use"

    def test_empty_lab_name_adds_warning(self):
        state = process_submission(self._make_raw(raw_lab_name=""))
        assert len(state.warnings) > 0

    # ── Real submission simulations ──────────────────────────────────

    def test_real_submission_ahfachkee(self):
        """Simulates Ahfachkee School submission (tribal school, Wildfires lab)."""
        raw = RawInput(
            raw_lab_name="wildfire unit",
            raw_project_description="Students mapped fire risk zones near the reservation.",
            raw_student_count_text="22",
            raw_community_partners="Partnered with the Seminole Tribe fire department.",
            raw_location="Clewiston, FL",
            submission_source="jotform_import",
        )
        ctx = TeacherContext(
            school_name="Ahfachkee Day School",
            city="Clewiston",
            state_province="FL",
            country="US",
            school_type=SchoolType.TRIBAL,
        )
        state = process_submission(raw, ctx)
        assert state.structured_intake.canonical_lab_name == "Wildfires"
        assert state.structured_intake.track == Track.B
        assert state.structured_intake.num_students_estimate == 22
        assert state.teacher_context.school_type == SchoolType.TRIBAL

    def test_real_submission_enroads_500_plus(self):
        """Simulates En-ROADS submission with 500+ students (large school)."""
        raw = RawInput(
            raw_lab_name="en-roads carbon simulation",
            raw_project_description="Whole-school En-ROADS assembly and student action teams.",
            raw_student_count_text="500+",
            raw_community_partners="",
        )
        state = process_submission(raw)
        si = state.structured_intake
        assert si.track == Track.A
        assert si.num_students_min == 500
        assert si.num_students_max is None
        assert si.num_students_estimate == 500

    def test_real_submission_civics_vague_count(self):
        """Simulates Civics submission with qualitative count."""
        raw = RawInput(
            raw_lab_name="civics climate action project",
            raw_project_description="Students lobbied local officials on plastic bag ban.",
            raw_student_count_text="about 30",
            raw_community_partners="Worked with city council and local environmental nonprofit.",
        )
        state = process_submission(raw)
        si = state.structured_intake
        assert si.canonical_lab_name == "Civics Climate Action"
        assert si.num_students_estimate == 30
        assert si.num_students_min is None  # "about" = approximate, no hard min
        assert len(si.community_partnerships) >= 1


    def test_grade_band_from_student_count_text(self):
        """Grade band parsed from raw_student_count_text (e.g. '30, grades 9-12')."""
        raw = RawInput(
            raw_lab_name="wildfires",
            raw_student_count_text="30, grades 9-12",
        )
        state = process_submission(raw)
        assert state.structured_intake.grade_band == GradeBand.HIGH

    def test_grade_band_unknown_when_no_grade_info(self):
        """If no grade info is present anywhere, grade_band stays UNKNOWN."""
        raw = RawInput(
            raw_lab_name="agriculture",
            raw_student_count_text="25",
        )
        state = process_submission(raw)
        assert state.structured_intake.grade_band == GradeBand.UNKNOWN

    def test_teacher_context_disaggregation_fields_preserved(self):
        """school_locale, school_type, country from teacher_context survive process_submission."""
        raw = RawInput(raw_lab_name="sea level rise", raw_student_count_text="18")
        ctx = TeacherContext(
            school_name="Test School",
            city="Miami",
            state_province="FL",
            country="US",
            school_locale=SchoolLocale.URBAN,
            school_type=SchoolType.PUBLIC,
            title1_status="yes",
        )
        state = process_submission(raw, ctx)
        tc = state.teacher_context
        assert tc.school_locale == SchoolLocale.URBAN
        assert tc.school_type == SchoolType.PUBLIC
        assert tc.country == "US"
        assert tc.title1_status == "yes"
        # These live on teacher_context, not structured_intake — confirm no duplication
        assert not hasattr(state.structured_intake, "school_locale")
        assert not hasattr(state.structured_intake, "country")

    def test_grade_band_from_additional_notes_fallback(self):
        """If raw_student_count_text has no grade info, check raw_additional_notes."""
        raw = RawInput(
            raw_lab_name="civics",
            raw_student_count_text="22",
            raw_additional_notes="This is a middle school class, grades 6-8.",
        )
        state = process_submission(raw)
        assert state.structured_intake.grade_band == GradeBand.MIDDLE


# ═════════════════════════════════════════
# 7. PARSE_GRADE_REFERENCE
# ═════════════════════════════════════════

class TestParseGradeReference:

    def test_year_6_elementary(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 6")
        assert r.normalized_grade == "Year6"
        assert r.grade_band == "elementary"

    def test_year_7_middle(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 7")
        assert r.normalized_grade == "Year7"
        assert r.grade_band == "middle"

    def test_myp_3_middle(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("MYP 3")
        assert r.normalized_grade == "MYP3"
        assert r.grade_band == "middle"

    def test_dp_1_high(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("DP 1")
        assert r.normalized_grade == "11"
        assert r.grade_band == "high"

    def test_us_grade_7(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Grade 7")
        assert r.normalized_grade == "7"
        assert r.grade_band == "middle"

    def test_us_ordinal_9th(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("9th grade")
        assert r.normalized_grade == "9"
        assert r.grade_band == "high"

    def test_kindergarten(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("K")
        assert r.normalized_grade == "K"
        assert r.grade_band == "elementary"

    def test_grade_range_6_8_middle(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("6-8")
        assert r.normalized_grade == "6-8"
        assert r.grade_band == "middle"

    def test_grade_range_9_12_high(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("9-12")
        assert r.normalized_grade == "9-12"
        assert r.grade_band == "high"

    def test_mixed_band_range(self):
        """5-8 spans elementary and middle — expect 'mixed'."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("5-8")
        assert r.normalized_grade == "5-8"
        assert r.grade_band == "mixed"

    def test_empty_returns_unknown(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("")
        assert r.normalized_grade == ""
        assert r.grade_band == "unknown"

    def test_raw_preserved(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 7")
        assert r.raw == "Year 7"



# ═════════════════════════════════════════
# 8. _IS_TITLE1 NORMALIZATION
# ═════════════════════════════════════════

class TestIsTitle1:
    """_is_title1() must handle every reasonable variant of 'yes'."""

    def test_lowercase_yes(self):
        assert _is_title1(TeacherContext(title1_status="yes")) is True

    def test_titlecase_yes(self):
        assert _is_title1(TeacherContext(title1_status="Yes")) is True

    def test_uppercase_yes(self):
        assert _is_title1(TeacherContext(title1_status="YES")) is True

    def test_yes_with_whitespace(self):
        assert _is_title1(TeacherContext(title1_status="  yes  ")) is True

    def test_boolean_true(self):
        ctx = TeacherContext()
        ctx.title1_status = True  # type: ignore[assignment]
        assert _is_title1(ctx) is True

    def test_integer_1(self):
        ctx = TeacherContext()
        ctx.title1_status = 1  # type: ignore[assignment]
        assert _is_title1(ctx) is True

    def test_no_returns_false(self):
        assert _is_title1(TeacherContext(title1_status="no")) is False

    def test_unknown_returns_false(self):
        assert _is_title1(TeacherContext(title1_status="unknown")) is False

    def test_default_returns_false(self):
        assert _is_title1(TeacherContext()) is False

    def test_boolean_false(self):
        ctx = TeacherContext()
        ctx.title1_status = False  # type: ignore[assignment]
        assert _is_title1(ctx) is False

    def test_integer_0_returns_false(self):
        ctx = TeacherContext()
        ctx.title1_status = 0  # type: ignore[assignment]
        assert _is_title1(ctx) is False


# ═════════════════════════════════════════
# 9. INFER_PROJECT_TYPE
# ═════════════════════════════════════════

class TestInferProjectType:
    """Deterministic keyword matching — no LLM required."""

    def test_composting_description(self):
        assert infer_project_type("Students built a composting bin", "Agriculture") == "Composting program"

    def test_solar_renewable(self):
        assert infer_project_type("We installed solar panels on the school roof", "Renewable Energy") == "Renewable energy installation"

    def test_policy_letter(self):
        assert infer_project_type("Students wrote letters to the city council advocating for change", "Civics") == "Policy advocacy / letter writing"

    def test_garden(self):
        assert infer_project_type("We created a school garden and grew vegetables", "Agriculture") == "School/community garden"

    def test_unknown_returns_other(self):
        assert infer_project_type("Students did a project about climate", "Floods and Droughts") == "Other"

    def test_lab_name_hint_used_when_description_vague(self):
        # Description is vague; lab_name contains the composting signal
        assert infer_project_type("We did our project", "Composting program for agriculture") == "Composting program"

    def test_tree_planting(self):
        assert infer_project_type("Students planted trees around the school grounds", "") == "Tree planting / reforestation"

    def test_recycling(self):
        assert infer_project_type("We launched a recycling drive in every classroom", "") == "Recycling program"

    def test_habitat_restoration(self):
        assert infer_project_type("Removed invasive species from the school wetland", "Invasive Species") == "Habitat restoration / invasive species removal"

    def test_none_description_safe(self):
        """None inputs must not raise — return 'Other' or match on lab_name."""
        result = infer_project_type(None, None)
        assert isinstance(result, str)

    def test_empty_strings_safe(self):
        result = infer_project_type("", "")
        assert result == "Other"


# ═════════════════════════════════════════
# 10. INFER_SUSTAINED_ACTION
# ═════════════════════════════════════════

class TestInferSustainedAction:
    """True / False / None based on keyword signals."""

    def test_as_a_result_is_true(self):
        assert infer_sustained_action(
            "The school now has a composting bin as a result of our project", ""
        ) is True

    def test_installed_permanently_is_true(self):
        assert infer_sustained_action(
            "Students installed solar panels permanently on the gymnasium", ""
        ) is True

    def test_ongoing_in_notes_is_true(self):
        """Signal in additional_notes should be detected."""
        assert infer_sustained_action("Students did a project.", "The program is ongoing.") is True

    def test_annual_event_is_true(self):
        assert infer_sustained_action("We hold an annual composting day at our school.", "") is True

    def test_one_time_presentation_is_false(self):
        assert infer_sustained_action(
            "Students gave a one-time presentation to the school assembly", ""
        ) is False

    def test_single_event_is_false(self):
        assert infer_sustained_action("This was a single event on Earth Day.", "") is False

    def test_vague_description_is_none(self):
        assert infer_sustained_action(
            "Students learned about climate change and made posters", ""
        ) is None

    def test_both_none_inputs_safe(self):
        """None inputs must not raise."""
        result = infer_sustained_action(None, None)
        assert result is None

    def test_empty_strings_safe(self):
        result = infer_sustained_action("", "")
        assert result is None


# ═════════════════════════════════════════
# 11. INFER_EQUITY_FLAG
# ═════════════════════════════════════════

class TestInferEquityFlag:
    """Title I, equity keywords, and school-type heuristic."""

    def test_title1_lowercase_is_true(self):
        ctx = TeacherContext(title1_status="yes", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(ctx, "Students planted trees") is True

    def test_title1_uppercase_is_true(self):
        ctx = TeacherContext(title1_status="YES", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(ctx, "Students did a composting project") is True

    def test_title1_titlecase_is_true(self):
        ctx = TeacherContext(title1_status="Yes", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(ctx, "Awareness campaign") is True

    def test_food_desert_in_description_is_true(self):
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(ctx, "Our school is in a food desert with no access to fresh produce") is True

    def test_equity_keyword_only_in_additional_notes_is_true(self):
        """If the keyword appears only in additional_notes (not description), it must still fire."""
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(
            ctx,
            project_description="Students did a garden project.",
            additional_notes="Our community is a frontline environmental justice community.",
        ) is True

    def test_indigenous_keyword_in_notes_is_true(self):
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        assert infer_equity_flag(
            ctx,
            project_description="Habitat restoration near the school.",
            additional_notes="This school serves an indigenous community.",
        ) is True

    def test_private_school_no_equity_keywords_is_false(self):
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PRIVATE)
        assert infer_equity_flag(ctx, "Students presented their project to parents") is False

    def test_montessori_no_equity_keywords_is_false(self):
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.MONTESSORI)
        assert infer_equity_flag(ctx, "Students did a composting project") is False

    def test_unknown_school_no_keywords_is_none(self):
        ctx = TeacherContext()  # defaults: school_type=UNKNOWN, title1_status="unknown"
        assert infer_equity_flag(ctx, "Students did a composting project") is None

    def test_none_description_safe(self):
        """None description must not raise."""
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        result = infer_equity_flag(ctx, None)
        assert result is None

    def test_none_notes_safe(self):
        """None additional_notes must not raise."""
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        result = infer_equity_flag(ctx, "Students learned about floods.", None)
        assert result is None

    def test_title1_overrides_private_school(self):
        """Title I always wins, even if school type is PRIVATE."""
        ctx = TeacherContext(title1_status="yes", school_type=SchoolType.PRIVATE)
        assert infer_equity_flag(ctx, "No equity keywords here") is True


# ═════════════════════════════════════════
# 12. PROCESS_SUBMISSION — NEW FIELD INTEGRATION
# ═════════════════════════════════════════

class TestProcessSubmissionNewFields:
    """Integration tests: all three new fields populated correctly end-to-end."""

    def test_composting_title1_all_three_fields(self):
        """Full integration: composting + Title I school → all three new fields correct."""
        raw = RawInput(
            raw_lab_name="agriculture",
            raw_student_count_text="28",
            raw_project_description=(
                "We built a composting bin in our school garden as a result of the lab. "
                "The bin is now maintained by the custodial staff permanently."
            ),
            raw_additional_notes="Our school serves a low-income community.",
            raw_community_partners="Local food bank",
        )
        ctx = TeacherContext(title1_status="yes", school_type=SchoolType.PUBLIC)
        state = process_submission(raw, teacher_context=ctx)

        assert state.structured_intake.project_type == "Composting program"
        assert state.structured_intake.equity_flag is True
        assert state.structured_intake.sustained_action is True

    def test_project_type_set_on_basic_submission(self):
        raw = RawInput(
            raw_lab_name="renewable energy",
            raw_student_count_text="25",
            raw_project_description="Students installed solar panels on the school roof.",
        )
        state = process_submission(raw)
        assert state.structured_intake.project_type == "Renewable energy installation"

    def test_sustained_action_false_on_one_off(self):
        raw = RawInput(
            raw_lab_name="civics",
            raw_student_count_text="30",
            raw_project_description="Students gave a one-time presentation to the city council.",
        )
        state = process_submission(raw)
        assert state.structured_intake.sustained_action is False

    def test_equity_flag_from_additional_notes_only(self):
        """Equity keyword only in additional_notes (not description) must still flag True."""
        raw = RawInput(
            raw_lab_name="agriculture",
            raw_student_count_text="20",
            raw_project_description="Students grew vegetables in the school garden.",
            raw_additional_notes="Our school is located in a food desert.",
        )
        ctx = TeacherContext(title1_status="no", school_type=SchoolType.PUBLIC)
        state = process_submission(raw, teacher_context=ctx)
        assert state.structured_intake.equity_flag is True

    def test_equity_flag_none_when_no_signal(self):
        raw = RawInput(
            raw_lab_name="sea level rise",
            raw_student_count_text="18",
            raw_project_description="Students measured coastal erosion near the school.",
        )
        ctx = TeacherContext()  # UNKNOWN school, unknown title1
        state = process_submission(raw, teacher_context=ctx)
        assert state.structured_intake.equity_flag is None

    def test_project_type_other_when_no_match(self):
        raw = RawInput(
            raw_lab_name="floods and droughts",
            raw_student_count_text="22",
            raw_project_description="Students studied historical drought data.",
        )
        state = process_submission(raw)
        assert state.structured_intake.project_type == "Other"

    def test_new_fields_present_on_minimal_submission(self):
        """Even a bare-minimum submission must populate all three fields without raising."""
        raw = RawInput(raw_lab_name="wildfires", raw_student_count_text="15")
        state = process_submission(raw)
        si = state.structured_intake
        assert isinstance(si.project_type, str)
        assert si.sustained_action is None   # no signal
        assert si.equity_flag is None        # no signal


# ═════════════════════════════════════════
# 13. PARSE_GRADE_REFERENCE — NEW CASES
# ═════════════════════════════════════════

class TestParseGradeReferenceExtended:
    """K-ranges, UK Year semantics, and edge cases added in cleanup pass."""

    # ── K-range tests (bug fix: was misclassified as elementary before) ──

    def test_k12_is_mixed(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("K-12")
        assert r.normalized_grade == "K-12"
        assert r.grade_band == "mixed"

    def test_k8_is_mixed(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("K-8")
        assert r.normalized_grade == "K-8"
        assert r.grade_band == "mixed"

    def test_k5_is_elementary(self):
        """K-5 spans only elementary grades → elementary band."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("K-5")
        assert r.normalized_grade == "K-5"
        assert r.grade_band == "elementary"

    def test_kindergarten_range_hyphen_variant(self):
        """Kindergarten-12 should behave like K-12."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Kindergarten-12")
        assert r.normalized_grade == "K-12"
        assert r.grade_band == "mixed"

    def test_single_k_still_elementary(self):
        """Plain 'K' (no range) must not be broken by K-range check."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("K")
        assert r.normalized_grade == "K"
        assert r.grade_band == "elementary"

    # ── UK Year normalization semantics ──────────────────────────────

    def test_uk_year_normalized_grade_is_prefixed(self):
        """UK Year values must use 'YearN' prefix, not bare number, to avoid
        false interpretation as a US grade by downstream consumers."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 9")
        assert r.normalized_grade == "Year9"
        assert r.grade_band == "middle"

    def test_uk_year_10_is_high(self):
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 10")
        assert r.normalized_grade == "Year10"
        assert r.grade_band == "high"

    def test_uk_year_6_band_unaffected_by_rename(self):
        """Band logic must be unchanged despite normalized_grade rename."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 6")
        assert r.grade_band == "elementary"

    def test_uk_year_not_confused_with_us_grade(self):
        """'Year 7' normalized_grade must NOT be bare '7' (which looks like US grade 7)."""
        from agent2 import parse_grade_reference
        r = parse_grade_reference("Year 7")
        assert r.normalized_grade != "7", (
            "normalized_grade 'Year7' must not be bare '7' to avoid US-grade confusion"
        )


# ═════════════════════════════════════════
# 14. INFER_PROJECT_TYPE — TIGHTENED TRIGGERS
# ═════════════════════════════════════════

class TestInferProjectTypeTightened:
    """Edge-case tests for triggers that were tightened in cleanup pass."""

    def test_presentation_alone_is_other(self):
        """'presentation' alone must NOT trigger Awareness — too generic."""
        result = infer_project_type(
            "Students gave a class presentation on flood risk.", ""
        )
        assert result == "Other", (
            f"'presentation' alone should be Other, got {result!r}"
        )

    def test_presentation_with_public_context_is_awareness(self):
        """'presentation' + 'public' context SHOULD trigger Awareness."""
        result = infer_project_type(
            "Students created a public presentation for the community fair.", ""
        )
        assert result == "Awareness / communications campaign"

    def test_display_alone_is_other(self):
        """'display' alone must NOT trigger Awareness."""
        result = infer_project_type(
            "Students created a display board for the science fair.", ""
        )
        assert result == "Other", (
            f"'display' alone should be Other, got {result!r}"
        )

    def test_display_with_community_context_is_awareness(self):
        """'display' + 'community' context SHOULD trigger Awareness."""
        result = infer_project_type(
            "Students put up a community display about sea level rise in the town library.", ""
        )
        assert result == "Awareness / communications campaign"

    def test_curriculum_alone_is_other(self):
        """'curriculum' alone must NOT trigger Curriculum integration — too generic."""
        result = infer_project_type(
            "This project was integrated into the science curriculum.", ""
        )
        assert result == "Other", (
            f"'curriculum' alone should be Other, got {result!r}"
        )

    def test_curriculum_with_life_cycle_is_curriculum_integration(self):
        """'curriculum' + 'life cycle' SHOULD trigger Curriculum integration."""
        result = infer_project_type(
            "Students conducted a life cycle analysis as part of their curriculum.", ""
        )
        assert result == "Curriculum integration / life cycle analysis"

    def test_life_cycle_without_curriculum_still_matches(self):
        """'life cycle' alone (without 'curriculum') must still match."""
        result = infer_project_type(
            "Students performed a full life cycle analysis of plastic packaging.", ""
        )
        assert result == "Curriculum integration / life cycle analysis"

    def test_awareness_keyword_still_works(self):
        """Tightening must not break the core 'awareness' trigger."""
        result = infer_project_type(
            "Students ran an awareness campaign about drought in their school.", ""
        )
        assert result == "Awareness / communications campaign"

    def test_poster_still_triggers_awareness(self):
        """'poster' should remain a standalone trigger for Awareness."""
        result = infer_project_type(
            "Students designed and distributed informational posters.", ""
        )
        assert result == "Awareness / communications campaign"


# ═════════════════════════════════════════
# 15. INFER_SUSTAINED_ACTION — EDGE CASES
# ═════════════════════════════════════════

class TestInferSustainedActionEdgeCases:
    """Verify 'as a result' no longer overfires, and weak causal language → None."""

    def test_as_a_result_alone_is_none(self):
        """'as a result' in generic causal context must NOT fire True."""
        result = infer_sustained_action(
            "As a result of our research, students learned about drought cycles.", ""
        )
        assert result is None, (
            f"Weak causal 'as a result' should be None, got {result!r}"
        )

    def test_as_a_result_with_now_has_is_true(self):
        """'now has ... as a result' — the 'now has' signal correctly fires True."""
        result = infer_sustained_action(
            "The school now has a composting system as a result of the project.", ""
        )
        assert result is True

    def test_weak_outcome_language_is_none(self):
        """Sentences describing learning outcomes must not be misread as sustained action."""
        result = infer_sustained_action(
            "Students found that composting reduces food waste significantly.", ""
        )
        assert result is None

    def test_past_tense_completed_project_is_false(self):
        """'completed' signals the project ended — should return False."""
        result = infer_sustained_action(
            "Students completed their project at the end of the semester.", ""
        )
        assert result is False

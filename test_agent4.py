"""
test_agent4.py
TCImpact — Agent 4 Test Suite

Tests use realistic inputs drawn from real TCI Jotform submission patterns.
All tests are deterministic (no LLM calls required).

Run all tests:
    python -m pytest test_agent4.py -v

Run with LLM (optional):
    LIVE_LLM=1 python -m pytest test_agent4.py -v
"""

import pytest

from agent4 import (
    JF_CONSENT,
    JF_EMAIL,
    JF_HIGHLIGHTS,
    JF_LAB,
    JF_MAILING_ADDRESS,
    JF_MERCH_CONSENT,
    JF_NAME,
    JF_OVERVIEW,
    JF_PHONE,
    JF_SCHOOL,
    JF_STUDENT_COUNT,
    JF_SUBMISSION_DATE,
    JF_TOPIC,
    JF_UPLOAD,
    JOTFORM_BLANK_FIELDS,
    JOTFORM_PRIVACY_NOTE,
    MAX_REALISTIC_STUDENT_COUNT,
    build_funder_summary_deterministic,
    build_jotform_draft,
    build_logic_model,
    build_map_export,
    run_agent4,
    _is_nonsense,
    _is_title1,
    _safe_student_count,
    _best_student_count,
    _scrub_pii,
)
from project_state import (
    CommunityPartner,
    GradeBand,
    ImpactMetrics,
    LogicModel,
    Phase,
    ProjectState,
    RawInput,
    Reporting,
    SchoolLocale,
    SchoolType,
    StructuredIntake,
    TeacherContext,
    Track,
)


# ─────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────

def _make_track_b_state(
    project_type: str = "Composting program",
    student_count: int = 28,
    school_name: str = "Jefferson Montessori",
    city: str = "Norwalk",
    country: str = "US",
    title1_status: str = "yes",
    school_type: SchoolType = SchoolType.MONTESSORI,
    partners: list = None,
    sustained: bool = True,
    equity: bool = True,
    description: str = "Students built a composting bin that is now maintained permanently.",
    notes: str = "Our school serves a low-income community.",
) -> ProjectState:
    """Build a realistic Track B ProjectState for testing."""
    if partners is None:
        partners = [CommunityPartner(name="Local Food Bank", partner_type="NGO")]

    state = ProjectState(
        raw_input=RawInput(
            raw_lab_name="agriculture lab",
            raw_project_description=description,
            raw_student_count_text=str(student_count),
            raw_additional_notes=notes,
            raw_community_partners="Local food bank",
        ),
        teacher_context=TeacherContext(
            school_name=school_name,
            city=city,
            country=country,
            title1_status=title1_status,
            school_type=school_type,
            school_locale=SchoolLocale.URBAN,
        ),
    )
    state.structured_intake = StructuredIntake(
        canonical_lab_name="Agriculture and Climate Change",
        canonical_lab_id=2,
        lab_match_confidence=0.95,
        track=Track.B,
        num_students_min=25,
        num_students_max=30,
        num_students_estimate=student_count,
        num_students_display=str(student_count),
        thematic_topic="Food & Land Use",
        project_type=project_type,
        grade_band=GradeBand.HIGH,
        community_partnerships=partners,
        sustained_action=sustained,
        equity_flag=equity,
    )
    state.impact_metrics = ImpactMetrics(
        impact_track=Track.B,
        reach_estimate=student_count,
        behavior_change_proxy="Composting program -- score 9/10 (High)",
        awareness_scale="High -- measurable, lasting behavior change expected",
        partnership_count=len(partners),
        community_score_total=72.0,
        community_score_json={"reach": 5, "depth": 25, "equity": 25, "sustainability": 12, "total": 67},
        methodology_notes="Estimated reach: 28 people. Partnering with Local Food Bank.",
    )
    return state


def _make_track_a_state(
    co2_lbs: float = 12500.0,
    student_count: int = 22,
    city: str = "Boston",
    country: str = "US",
) -> ProjectState:
    """Build a realistic Track A (En-ROADS) ProjectState for testing."""
    state = ProjectState(
        raw_input=RawInput(
            raw_lab_name="en-roads",
            raw_project_description=(
                "Students ran En-ROADS simulations to model CO₂ reductions "
                "from school-wide energy efficiency improvements."
            ),
            raw_student_count_text=str(student_count),
        ),
        teacher_context=TeacherContext(
            school_name="Boston Latin School",
            city=city,
            country=country,
            title1_status="no",
            school_type=SchoolType.PUBLIC,
        ),
    )
    state.structured_intake = StructuredIntake(
        canonical_lab_name="Climate Impacts and Solutions with En-ROADS",
        canonical_lab_id=1,
        lab_match_confidence=1.0,
        track=Track.A,
        num_students_estimate=student_count,
        num_students_display=str(student_count),
        thematic_topic="Climate Solutions & Modeling",
        project_type="Energy reduction/efficiency",
        grade_band=GradeBand.HIGH,
        sustained_action=False,
        equity_flag=False,
    )
    state.impact_metrics = ImpactMetrics(
        impact_track=Track.A,
        co2_reduction_lbs=co2_lbs,
        co2_reduction_methodology='{"steps": [], "total_co2_reduction_lbs": 12500.0}',
        co2_target_met=(co2_lbs >= 10000),
        epa_emissions_factor_used="Electricity savings",
        methodology_notes="Students calculated CO₂ reduction using EPA factors.",
    )
    return state


# ═════════════════════════════════════════
# 1. INPUT HELPERS
# ═════════════════════════════════════════

class TestSafeStudentCount:

    def test_normal_count(self):
        assert _safe_student_count(28) == 28

    def test_string_count(self):
        assert _safe_student_count("30") == 30

    def test_comma_formatted(self):
        assert _safe_student_count("1,200") == 1200

    def test_zero_is_none(self):
        assert _safe_student_count(0) is None

    def test_none_is_none(self):
        assert _safe_student_count(None) is None

    def test_over_limit_is_none(self):
        assert _safe_student_count(MAX_REALISTIC_STUDENT_COUNT + 1) is None

    def test_exactly_at_limit_is_valid(self):
        assert _safe_student_count(MAX_REALISTIC_STUDENT_COUNT) == MAX_REALISTIC_STUDENT_COUNT

    def test_nonsense_string_is_none(self):
        assert _safe_student_count("many students") is None

    def test_negative_is_none(self):
        assert _safe_student_count(-5) is None


class TestBestStudentCount:

    def test_prefers_estimate_over_max(self):
        intake = {"num_students_estimate": 28, "num_students_max": 30}
        assert _best_student_count(intake) == 28

    def test_falls_back_to_max(self):
        intake = {"num_students_max": 30}
        assert _best_student_count(intake) == 30

    def test_falls_back_to_min(self):
        intake = {"num_students_min": 10}
        assert _best_student_count(intake) == 10

    def test_empty_dict_is_none(self):
        assert _best_student_count({}) is None

    def test_unrealistic_estimate_skipped(self):
        intake = {"num_students_estimate": 99999, "num_students_max": 30}
        assert _best_student_count(intake) == 30


# ═════════════════════════════════════════
# 2. LOGIC MODEL — TRACK B
# ═════════════════════════════════════════

class TestLogicModelTrackB:

    def test_returns_logic_model_instance(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert isinstance(lm, LogicModel)

    def test_inputs_contain_lab_name(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("Agriculture and Climate Change" in s for s in lm.inputs)

    def test_inputs_contain_student_count(self):
        state = _make_track_b_state(student_count=28)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("28" in s for s in lm.inputs)

    def test_inputs_contain_partner_name(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("Local Food Bank" in s for s in lm.inputs)

    def test_activities_are_non_empty(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert len(lm.activities) > 0

    def test_outputs_are_non_empty(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert len(lm.outputs) > 0

    def test_sustained_action_appears_in_intermediate_outcomes(self):
        state = _make_track_b_state(sustained=True)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("continue" in s.lower() or "lasting" in s.lower() for s in lm.intermediate_outcomes)

    def test_no_sustained_action_does_not_add_outcome(self):
        state = _make_track_b_state(sustained=False)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert not any("continue beyond" in s.lower() for s in lm.intermediate_outcomes)

    def test_equity_note_set_for_title1(self):
        state = _make_track_b_state(title1_status="yes")
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert lm.equity_note != ""
        assert "equity" in lm.equity_note.lower() or "title" in lm.equity_note.lower()

    def test_equity_note_empty_when_no_equity(self):
        state = _make_track_b_state(title1_status="no", equity=False)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert lm.equity_note == ""

    def test_logic_model_text_renders_non_empty(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        text = lm.to_text()
        assert isinstance(text, str)
        assert len(text) > 20

    def test_policy_outcome_in_intermediate_when_policy_flag(self):
        state = _make_track_b_state()
        state.impact_metrics.policy_influence_flag = True
        state.impact_metrics.policy_description = "City council adopted a composting resolution."
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("composting resolution" in s.lower() for s in lm.intermediate_outcomes)


# ═════════════════════════════════════════
# 3. LOGIC MODEL — TRACK A
# ═════════════════════════════════════════

class TestLogicModelTrackA:

    def test_track_a_activities_reference_enroads(self):
        state = _make_track_a_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("en-roads" in s.lower() or "simulation" in s.lower() for s in lm.activities)

    def test_track_a_outputs_include_co2_figure(self):
        state = _make_track_a_state(co2_lbs=12500.0)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("12,500" in s or "12500" in s for s in lm.outputs)

    def test_track_a_inputs_contain_lab_name(self):
        state = _make_track_a_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert any("En-ROADS" in s for s in lm.inputs)

    def test_track_a_no_composting_activities(self):
        """Track A should use En-ROADS template, not composting template."""
        state = _make_track_a_state()
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(_intake_dict(state.structured_intake), _metrics_dict(state.impact_metrics))
        assert not any("compost" in s.lower() for s in lm.activities)


# ═════════════════════════════════════════
# 4. JOTFORM DRAFT
# ═════════════════════════════════════════

class TestJotformDraft:

    def test_returns_dict(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert isinstance(draft, dict)

    def test_uses_real_jotform_header_for_lab(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert JF_LAB in draft
        assert "Agriculture and Climate Change" in draft[JF_LAB]

    def test_uses_real_jotform_header_for_school(self):
        state = _make_track_b_state(school_name="Jefferson Montessori")
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert JF_SCHOOL in draft
        assert "Jefferson Montessori" in draft[JF_SCHOOL]

    def test_student_count_populated(self):
        state = _make_track_b_state(student_count=28)
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "28" in draft[JF_STUDENT_COUNT]

    def test_overview_from_raw_project_description(self):
        state = _make_track_b_state(description="Students built a composting bin.")
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "composting bin" in draft[JF_OVERVIEW].lower()

    def test_highlights_contains_reach(self):
        state = _make_track_b_state(student_count=28)
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "28" in draft[JF_HIGHLIGHTS] or "reach" in draft[JF_HIGHLIGHTS].lower()

    def test_name_is_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_NAME] == ""

    def test_email_is_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_EMAIL] == ""

    def test_phone_is_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_PHONE] == ""

    def test_upload_field_is_empty_string(self):
        """Upload URLs must never be generated or stored by this system."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_UPLOAD] == ""

    def test_mailing_address_is_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_MAILING_ADDRESS] == ""

    def test_consent_is_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_CONSENT] == ""

    def test_highlights_mentions_artifacts_not_uploaded(self):
        """Must not imply student media is stored in this system."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        highlights = draft[JF_HIGHLIGHTS].lower()
        assert "official" in highlights or "jotform" in highlights

    def test_submission_date_is_populated(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert draft[JF_SUBMISSION_DATE] != ""

    def test_no_fabricated_upload_urls(self):
        """No jotform.com or http upload URLs should appear anywhere in the draft."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        all_values = " ".join(str(v) for v in draft.values())
        assert "jotform.com/uploads" not in all_values
        assert "http" not in all_values or "official" in all_values.lower()


# ═════════════════════════════════════════
# 5. FUNDER SUMMARY
# ═════════════════════════════════════════

class TestFunderSummaryDeterministic:

    def test_returns_non_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert isinstance(summary, str)
        assert len(summary) > 30

    def test_mentions_lab_name(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "Agriculture and Climate Change" in summary

    def test_mentions_school(self):
        state = _make_track_b_state(school_name="Jefferson Montessori")
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "Jefferson Montessori" in summary

    def test_mentions_student_count(self):
        state = _make_track_b_state(student_count=28)
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "28" in summary

    def test_mentions_equity_for_title1(self):
        state = _make_track_b_state(title1_status="yes")
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "equity" in summary.lower() or "title" in summary.lower() or "underserved" in summary.lower()

    def test_track_a_mentions_co2(self):
        state = _make_track_a_state(co2_lbs=12500.0)
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "12,500" in summary or "CO" in summary

    def test_track_a_mentions_target_met(self):
        state = _make_track_a_state(co2_lbs=12500.0)
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "target" in summary.lower() or "10,000" in summary

    def test_no_personal_data_in_summary(self):
        """Funder summary must not contain email addresses or phone numbers."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "@" not in summary
        assert "555" not in summary

    def test_sustained_action_mentioned(self):
        state = _make_track_b_state(sustained=True)
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "beyond" in summary.lower() or "lasting" in summary.lower() or "continue" in summary.lower()

    def test_minimal_state_does_not_raise(self):
        """Even with empty intake and metrics, should return a string."""
        summary = build_funder_summary_deterministic({}, {}, None)
        assert isinstance(summary, str)


# ═════════════════════════════════════════
# 6. MAP EXPORT — GATING
# ═════════════════════════════════════════

class TestMapExportGating:

    def test_map_export_empty_when_not_submitted(self):
        """Map must not be generated before Jotform is confirmed."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=False,
        )
        assert result == {}

    def test_map_export_empty_by_default(self):
        """Default is jotform_submitted=False — map is always gated."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert result == {}

    def test_map_export_generated_when_submitted(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_map_export_contains_lab_name(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["lab_name"] == "Agriculture and Climate Change"

    def test_map_export_contains_student_count(self):
        state = _make_track_b_state(student_count=28)
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["num_students"] == 28

    def test_map_export_contains_track(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["track"] == "B"

    def test_map_export_track_a(self):
        state = _make_track_a_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["track"] == "A"
        assert result["co2_reduction_lbs"] == 12500.0

    def test_map_export_no_email_or_address(self):
        """Map export must never contain personal data."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        keys = set(result.keys())
        assert "email" not in keys
        assert "phone" not in keys
        assert "address" not in keys
        assert "name" not in keys

    def test_map_export_lat_lng_are_none_placeholders(self):
        """Geocoding is out of scope for POC — coordinates must be None."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["lat"] is None
        assert result["lng"] is None

    def test_map_export_contains_city_and_country(self):
        state = _make_track_b_state(city="Norwalk", country="US")
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["city"] == "Norwalk"
        assert result["country"] == "US"


# ═════════════════════════════════════════
# 7. RUN_AGENT4 — INTEGRATION
# ═════════════════════════════════════════

class TestRunAgent4Integration:

    def test_returns_state(self):
        state = _make_track_b_state()
        result = run_agent4(state)
        assert result is state

    def test_reporting_logic_model_populated(self):
        state = _make_track_b_state()
        run_agent4(state)
        assert isinstance(state.reporting.logic_model, LogicModel)
        assert len(state.reporting.logic_model.activities) > 0

    def test_reporting_logic_model_text_populated(self):
        state = _make_track_b_state()
        run_agent4(state)
        assert isinstance(state.reporting.logic_model_text, str)
        assert len(state.reporting.logic_model_text) > 0

    def test_reporting_jotform_draft_populated(self):
        state = _make_track_b_state()
        run_agent4(state)
        assert isinstance(state.reporting.jotform_draft, dict)
        assert JF_LAB in state.reporting.jotform_draft

    def test_reporting_funder_summary_populated(self):
        state = _make_track_b_state()
        run_agent4(state)
        assert isinstance(state.reporting.funder_summary, str)
        assert len(state.reporting.funder_summary) > 20

    def test_map_export_empty_without_submission(self):
        state = _make_track_b_state()
        run_agent4(state, jotform_submitted=False)
        assert state.reporting.map_export_json == {}

    def test_map_export_populated_with_submission(self):
        state = _make_track_b_state()
        run_agent4(state, jotform_submitted=True)
        assert isinstance(state.reporting.map_export_json, dict)
        assert state.reporting.map_export_json.get("lab_name") == "Agriculture and Climate Change"

    def test_structured_intake_never_modified(self):
        """Agent 4 must never write to structured_intake."""
        state = _make_track_b_state()
        original_lab = state.structured_intake.canonical_lab_name
        run_agent4(state)
        assert state.structured_intake.canonical_lab_name == original_lab

    def test_impact_metrics_never_modified(self):
        """Agent 4 must never write to impact_metrics."""
        state = _make_track_b_state()
        original_reach = state.impact_metrics.reach_estimate
        run_agent4(state)
        assert state.impact_metrics.reach_estimate == original_reach

    def test_rerunning_overwrites_not_appends(self):
        """Running Agent 4 twice must produce identical output, not accumulated text."""
        state = _make_track_b_state()
        run_agent4(state)
        summary_first = state.reporting.funder_summary
        run_agent4(state)
        summary_second = state.reporting.funder_summary
        assert summary_first == summary_second

    def test_rerunning_jotform_draft_idempotent(self):
        state = _make_track_b_state()
        run_agent4(state)
        draft_first = dict(state.reporting.jotform_draft)
        run_agent4(state)
        draft_second = dict(state.reporting.jotform_draft)
        assert draft_first == draft_second

    def test_track_a_full_pipeline(self):
        state = _make_track_a_state(co2_lbs=12500.0)
        run_agent4(state, jotform_submitted=True)
        assert state.reporting.funder_summary != ""
        assert state.reporting.map_export_json.get("track") == "A"
        assert state.reporting.map_export_json.get("co2_reduction_lbs") == 12500.0

    def test_phase_not_modified_by_agent4(self):
        """Agent 4 must not advance the project phase."""
        state = _make_track_b_state()
        state.phase = Phase.IMPLEMENTING
        run_agent4(state)
        assert state.phase == Phase.IMPLEMENTING


# ═════════════════════════════════════════
# 8. REALISTIC SUBMISSION SIMULATIONS
# ═════════════════════════════════════════

class TestRealisticSubmissions:

    def test_ahfachkee_tribal_school_wildfire(self):
        """Simulates Ahfachkee Day School — tribal school, Wildfires lab, small cohort."""
        state = ProjectState(
            raw_input=RawInput(
                raw_lab_name="wildfire unit",
                raw_project_description="Students mapped fire risk zones near the reservation.",
                raw_student_count_text="22",
                raw_community_partners="Seminole Tribe fire department",
            ),
            teacher_context=TeacherContext(
                school_name="Ahfachkee Day School",
                city="Clewiston",
                state_province="FL",
                country="US",
                school_type=SchoolType.TRIBAL,
                title1_status="yes",
            ),
        )
        state.structured_intake = StructuredIntake(
            canonical_lab_name="Wildfires",
            track=Track.B,
            num_students_estimate=22,
            thematic_topic="Climate Impacts",
            project_type="Habitat restoration / invasive species removal",
            grade_band=GradeBand.MIDDLE,
            community_partnerships=[CommunityPartner(name="Seminole Tribe Fire Dept", partner_type="government")],
            sustained_action=True,
            equity_flag=True,
        )
        state.impact_metrics = ImpactMetrics(
            impact_track=Track.B,
            reach_estimate=22,
            partnership_count=1,
            community_score_total=67.0,
        )
        run_agent4(state, jotform_submitted=True)

        assert "Ahfachkee" in state.reporting.funder_summary
        assert state.reporting.map_export_json.get("equity_flag") is True
        assert state.reporting.jotform_draft[JF_SCHOOL] == "Ahfachkee Day School"

    def test_hershey_montessori_enroads(self):
        """Simulates Hershey Montessori — En-ROADS lab, above-target carbon reduction."""
        state = _make_track_a_state(co2_lbs=15000.0, student_count=12)
        state.teacher_context.school_name = "Hershey Montessori School"
        state.teacher_context.city = "Huntsburg"
        state.teacher_context.state_province = "OH"
        run_agent4(state, jotform_submitted=True)

        assert "15,000" in state.reporting.funder_summary or "15000" in state.reporting.funder_summary
        assert state.reporting.map_export_json.get("track") == "A"

    def test_civics_lab_policy_outcome(self):
        """Simulates civics lab with a documented policy outcome."""
        state = _make_track_b_state(
            project_type="Policy advocacy / letter writing",
            description="Students lobbied local officials on a plastic bag ban.",
        )
        state.impact_metrics.policy_influence_flag = True
        state.impact_metrics.policy_description = "City council adopted plastic bag ordinance."
        run_agent4(state)

        summary = state.reporting.funder_summary.lower()
        assert "policy" in summary or "ordinance" in summary
        logic_text = state.reporting.logic_model_text.lower()
        assert "policy" in logic_text or "ordinance" in logic_text

    def test_international_submission_zambia(self):
        """Simulates a submission from Zambia — international context."""
        state = _make_track_b_state(
            school_name="Lusaka Community School",
            city="Lusaka",
            country="Zambia",
        )
        run_agent4(state, jotform_submitted=True)

        assert "Lusaka" in state.reporting.funder_summary
        assert state.reporting.map_export_json.get("country") == "Zambia"

    def test_unrealistic_student_count_ignored(self):
        """A student count of 50,000 should be treated as a data entry error."""
        state = _make_track_b_state(student_count=28)
        state.structured_intake.num_students_estimate = 50000
        state.structured_intake.num_students_max = 30
        run_agent4(state)

        # Should fall back to num_students_max (30), not use 50,000
        draft_count = state.reporting.jotform_draft.get(JF_STUDENT_COUNT, "")
        assert "50,000" not in draft_count
        assert "50000" not in draft_count


# ═════════════════════════════════════════
# 9. _IS_TITLE1 NORMALIZATION
# ═════════════════════════════════════════

class TestIsTitle1:

    def test_lowercase_yes(self):
        assert _is_title1(TeacherContext(title1_status="yes")) is True

    def test_titlecase_yes(self):
        assert _is_title1(TeacherContext(title1_status="Yes")) is True

    def test_uppercase_yes(self):
        assert _is_title1(TeacherContext(title1_status="YES")) is True

    def test_boolean_true(self):
        ctx = TeacherContext()
        ctx.title1_status = True
        assert _is_title1(ctx) is True

    def test_integer_1(self):
        ctx = TeacherContext()
        ctx.title1_status = 1
        assert _is_title1(ctx) is True

    def test_no_is_false(self):
        assert _is_title1(TeacherContext(title1_status="no")) is False

    def test_unknown_is_false(self):
        assert _is_title1(TeacherContext(title1_status="unknown")) is False

    def test_none_context_is_false(self):
        assert _is_title1(None) is False

    def test_title1_yes_uppercase_triggers_equity_note_in_logic_model(self):
        state = _make_track_b_state(title1_status="YES", equity=False)
        from agent4 import _intake_dict, _metrics_dict
        lm = build_logic_model(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert lm.equity_note != ""

    def test_title1_yes_uppercase_appears_in_funder_summary(self):
        state = _make_track_b_state(title1_status="YES", equity=False)
        from agent4 import _intake_dict, _metrics_dict
        summary = build_funder_summary_deterministic(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
        )
        assert "equity" in summary.lower() or "title" in summary.lower()


# ═════════════════════════════════════════
# 10. PRIVACY METADATA IN JOTFORM DRAFT
# ═════════════════════════════════════════

class TestJotformDraftPrivacyMetadata:

    def test_privacy_note_key_present(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "_privacy_note" in draft

    def test_privacy_note_is_non_empty_string(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert isinstance(draft["_privacy_note"], str)
        assert len(draft["_privacy_note"]) > 20

    def test_blank_fields_list_present(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "_blank_fields" in draft
        assert isinstance(draft["_blank_fields"], list)
        assert len(draft["_blank_fields"]) > 0

    def test_blank_fields_includes_name_and_email(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        blank = draft["_blank_fields"]
        assert "Name" in blank
        assert "Email" in blank

    def test_personal_data_fields_are_empty_string_not_note(self):
        """Personal fields must be '' not a note string — note is in _privacy_note."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        for key in (JF_NAME, JF_EMAIL, JF_PHONE, JF_MAILING_ADDRESS, JF_CONSENT, JF_UPLOAD):
            assert draft[key] == "", f"Expected '' for {key}, got {draft[key]!r}"


# ═════════════════════════════════════════
# 11. PII SCRUBBER
# ═════════════════════════════════════════

class TestScrubPii:

    def test_email_removed(self):
        assert "[email removed]" in _scrub_pii("Contact me at teacher@school.org for more info.")

    def test_us_phone_removed(self):
        assert "[phone removed]" in _scrub_pii("Call us at (203) 555-1234 anytime.")

    def test_url_removed(self):
        assert "[link removed]" in _scrub_pii("See https://example.com/results for details.")

    def test_street_address_removed(self):
        result = _scrub_pii("We are located at 123 Main Street, Norwalk.")
        assert "[address removed]" in result

    def test_clean_text_unchanged(self):
        text = "Students composted food waste and tracked results weekly."
        assert _scrub_pii(text) == text

    def test_empty_string_safe(self):
        assert _scrub_pii("") == ""

    def test_pii_not_in_jotform_overview(self):
        """Email and phone in raw description must be scrubbed from draft overview."""
        state = _make_track_b_state(
            description="Email teacher@school.org or call (203) 555-9999 for project details."
        )
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        overview = draft[JF_OVERVIEW]
        assert "@" not in overview
        assert "555-9999" not in overview

    def test_pii_not_in_jotform_highlights(self):
        """Email and URL in notes must be scrubbed from draft highlights."""
        state = _make_track_b_state(
            notes="Contact us at admin@school.edu or visit http://school.edu/project"
        )
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        highlights = draft[JF_HIGHLIGHTS]
        assert "@" not in highlights
        assert "http://school.edu/project" not in highlights


# ═════════════════════════════════════════
# 12. NONSENSE INPUT GUARD
# ═════════════════════════════════════════

class TestIsNonsense:

    def test_empty_is_nonsense(self):
        assert _is_nonsense("") is True

    def test_whitespace_is_nonsense(self):
        assert _is_nonsense("   ") is True

    def test_single_char_is_nonsense(self):
        assert _is_nonsense("x") is True

    def test_repeated_chars_is_nonsense(self):
        assert _is_nonsense("aaaaaaaaaa") is True

    def test_punctuation_only_is_nonsense(self):
        assert _is_nonsense("????!!!") is True

    def test_valid_description_not_nonsense(self):
        assert _is_nonsense("Students built a composting bin.") is False

    def test_short_but_valid_not_nonsense(self):
        assert _is_nonsense("Yes") is False

    def test_nonsense_description_uses_structured_fallback(self):
        """Nonsense raw description must produce structured fallback, not echo the junk."""
        state = _make_track_b_state(description="zzzzzzzzzzz")
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "zzzzzzzzzzz" not in draft[JF_OVERVIEW]
        assert draft[JF_OVERVIEW] != ""  # fallback was used

    def test_boundary_punctuation_not_echoed(self):
        """Boundary-testing input like '!!!???###' must not appear in output."""
        state = _make_track_b_state(description="!!!???###")
        from agent4 import _intake_dict, _metrics_dict
        draft = build_jotform_draft(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.raw_input,
            state.teacher_context,
        )
        assert "!!!???###" not in draft[JF_OVERVIEW]


# ═════════════════════════════════════════
# 13. MAP EXPORT — EXPANDED FIELDS
# ═════════════════════════════════════════

class TestMapExportExpandedFields:

    def test_school_name_in_export(self):
        state = _make_track_b_state(school_name="Jefferson Montessori")
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["school_name"] == "Jefferson Montessori"

    def test_state_province_in_export(self):
        state = _make_track_b_state()
        state.teacher_context.state_province = "CT"
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["state_province"] == "CT"

    def test_project_duration_weeks_in_export(self):
        state = _make_track_b_state()
        state.structured_intake.project_duration_weeks = 8
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["project_duration_weeks"] == 8

    def test_submission_date_in_export(self):
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert "submission_date" in result
        assert isinstance(result["submission_date"], str)
        assert len(result["submission_date"]) == 10  # ISO format YYYY-MM-DD

    def test_no_personal_data_in_expanded_export(self):
        """Expanded fields must not introduce personal data."""
        state = _make_track_b_state()
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert "email" not in result
        assert "phone" not in result
        assert "address" not in result

    def test_duration_none_when_not_set(self):
        state = _make_track_b_state()
        state.structured_intake.project_duration_weeks = None
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["project_duration_weeks"] is None

    def test_city_and_country_still_present(self):
        """Original location fields must still be present after expansion."""
        state = _make_track_b_state(city="Norwalk", country="US")
        from agent4 import _intake_dict, _metrics_dict
        result = build_map_export(
            _intake_dict(state.structured_intake),
            _metrics_dict(state.impact_metrics),
            state.teacher_context,
            jotform_submitted=True,
        )
        assert result["city"] == "Norwalk"
        assert result["country"] == "US"

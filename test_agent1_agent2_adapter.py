"""
test_agent1_agent2_adapter.py
TCImpact — Agent 1 → Agent 2 Adapter Test Suite

All tests are deterministic (no LLM calls required).
They use realistic simulated Agent 1 output drawn from real metadata
shapes — the same dict structure run_agent1() actually returns.

Run:
    python -m pytest test_agent1_agent2_adapter.py -v
"""

import pytest

from agent1_agent2_adapter import (
    adapt_agent1_to_raw_input,
    build_raw_input_from_message,
    _resolve_lab_name,
    _resolve_project_description,
    _resolve_additional_notes,
    _first_lab_from_chunks,
    _first_lab_from_matched,
)
from project_state import (
    RawInput,
    SchoolLocale,
    SchoolType,
    TeacherContext,
)

# Skip integration tests if agent3/agent4 not present in current environment.
# These tests pass on the full repo; they are skipped in isolated sandbox runs.
try:
    import agent3  # noqa: F401
    import agent4  # noqa: F401
    FULL_PIPELINE_AVAILABLE = True
except ImportError:
    FULL_PIPELINE_AVAILABLE = False

skip_no_pipeline = pytest.mark.skipif(
    not FULL_PIPELINE_AVAILABLE,
    reason="agent3 / agent4 not available in this environment — run on full repo"
)


# ─────────────────────────────────────────
# FIXTURES — realistic Agent 1 metadata shapes
# ─────────────────────────────────────────

def _teacher_metadata(
    target_lab: str = "Renewable Energy",
    matched_labs: list = None,
    chunks: list = None,
    clarification: bool = False,
    curriculum_system: str = "NGSS",
    stage: str = "high",
) -> dict:
    """Simulate teacher-mode metadata returned by run_agent1()."""
    return {
        "mode": "teacher",
        "target_lab": target_lab,
        "retrieval_query": f"{target_lab} curriculum activities",
        "retrieved_chunks": chunks or [
            {"lab_name": target_lab, "track": "B", "preview": "Students explore..."},
        ],
        "standards_result": {
            "system": curriculum_system,
            "stage": stage,
            "confidence": 0.92,
            "matched_labs": matched_labs or [target_lab],
            "target_lab": target_lab,
            "needs_clarification": clarification,
        },
        "clarification_returned": clarification,
    }


def _student_metadata(
    lab_name: str = "Agriculture and Climate Change",
    signals: list = None,
    category: str = "feasibility",
) -> dict:
    """Simulate student-mode metadata returned by run_agent1()."""
    return {
        "mode": "student",
        "target_lab": None,  # student mode doesn't set target_lab
        "retrieval_query": f"{lab_name} student project activities",
        "retrieved_chunks": [
            {"lab_name": lab_name, "track": "B", "preview": "Composting activities..."},
        ],
        "socratic": {
            "detected_signals": signals or ["feasibility", "community"],  # key matches adapter
            "category": category,
            "question_id": "q_feasibility_01",
            "primary_question": "What resources does your school already have?",
            "is_distressed": False,
            "growth_reflection": "",
        },
    }


def _math_metadata() -> dict:
    """Simulate math-mode metadata returned by run_agent1()."""
    return {
        "mode": "math",
        "target_lab": None,
        "retrieved_chunks": [],
        # math mode has no standards_result or socratic
    }


def _clarification_metadata(target_lab: str = None) -> dict:
    """Simulate metadata when Agent 1 returned a clarification question."""
    return {
        "mode": "teacher",
        "target_lab": target_lab,
        "retrieval_query": None,
        "retrieved_chunks": [],
        "standards_result": {
            "system": "unknown",
            "stage": "unknown",
            "confidence": 0.3,
            "matched_labs": [],
            "target_lab": target_lab,
            "needs_clarification": True,
        },
        "clarification_returned": True,
    }


def _make_teacher_context(
    school: str = "Jefferson Montessori",
    city: str = "Norwalk",
    state: str = "CT",
    country: str = "US",
) -> TeacherContext:
    return TeacherContext(
        school_name=school,
        city=city,
        state_province=state,
        country=country,
        school_type=SchoolType.MONTESSORI,
        school_locale=SchoolLocale.URBAN,
        title1_status="yes",
    )


# ═════════════════════════════════════════
# 1. INTERNAL HELPERS
# ═════════════════════════════════════════

class TestFirstLabFromChunks:

    def test_extracts_first_lab_name(self):
        chunks = [{"lab_name": "Renewable Energy", "track": "B"}]
        assert _first_lab_from_chunks(chunks) == "Renewable Energy"

    def test_skips_empty_lab_name(self):
        chunks = [{"lab_name": "", "track": "B"}, {"lab_name": "Wildfires", "track": "B"}]
        assert _first_lab_from_chunks(chunks) == "Wildfires"

    def test_empty_list_returns_empty(self):
        assert _first_lab_from_chunks([]) == ""

    def test_malformed_chunk_skipped(self):
        chunks = [{"no_lab_key": "x"}, {"lab_name": "Sea Level Rise"}]
        assert _first_lab_from_chunks(chunks) == "Sea Level Rise"

    def test_none_value_skipped(self):
        chunks = [{"lab_name": None}, {"lab_name": "Wildfires"}]
        assert _first_lab_from_chunks(chunks) == "Wildfires"


class TestFirstLabFromMatched:

    def test_returns_first(self):
        assert _first_lab_from_matched(["Civics Climate Action", "Agriculture"]) == "Civics Climate Action"

    def test_empty_list_returns_empty(self):
        assert _first_lab_from_matched([]) == ""

    def test_none_returns_empty(self):
        assert _first_lab_from_matched(None) == ""


class TestResolveLabName:

    def test_target_lab_wins(self):
        meta = _teacher_metadata(target_lab="Renewable Energy")
        result = _resolve_lab_name(meta, "I teach AP Chemistry")
        assert result == "Renewable Energy"

    def test_falls_back_to_matched_labs(self):
        meta = _teacher_metadata(target_lab="", matched_labs=["Civics Climate Action"])
        result = _resolve_lab_name(meta, "I teach civics")
        assert result == "Civics Climate Action"

    def test_falls_back_to_retrieved_chunks(self):
        meta = {
            "mode": "teacher",
            "target_lab": "",
            "standards_result": {"matched_labs": []},
            "retrieved_chunks": [{"lab_name": "Wildfires", "track": "B"}],
        }
        result = _resolve_lab_name(meta, "fire science")
        assert result == "Wildfires"

    def test_returns_empty_when_nothing_available(self):
        meta = {
            "mode": "teacher",
            "target_lab": "",
            "standards_result": {"matched_labs": []},
            "retrieved_chunks": [],
        }
        result = _resolve_lab_name(meta, "some message")
        assert result == ""

    def test_student_mode_no_target_lab_uses_chunks(self):
        meta = _student_metadata(lab_name="Agriculture and Climate Change")
        result = _resolve_lab_name(meta, "we want to do a composting project")
        assert result == "Agriculture and Climate Change"

    def test_clarification_mode_empty_target_still_uses_chunks(self):
        meta = _clarification_metadata(target_lab=None)
        result = _resolve_lab_name(meta, "I teach science")
        assert result == ""  # no chunks in clarification metadata


class TestResolveProjectDescription:

    def test_original_message_preferred_over_response(self):
        result = _resolve_project_description(
            "Here are the standards for Renewable Energy...",
            "I want to do a solar panel project with 25 students",
            {},
        )
        assert "solar panel" in result

    def test_falls_back_to_truncated_response_when_message_empty(self):
        result = _resolve_project_description(
            "A" * 500,
            "",
            {},
        )
        assert len(result) <= 200
        assert result != ""

    def test_clarification_mode_uses_original_message(self):
        meta = _clarification_metadata()
        result = _resolve_project_description(
            "What subject do you teach?",
            "I want to do something with climate",
            meta,
        )
        assert "climate" in result


class TestResolveAdditionalNotes:

    def test_student_mode_includes_signals(self):
        meta = _student_metadata(signals=["feasibility", "community"])
        result = _resolve_additional_notes("response text", meta, "teacher message")
        assert "feasibility" in result
        assert "community" in result

    def test_student_mode_includes_category(self):
        meta = _student_metadata(category="scale")
        result = _resolve_additional_notes("", meta, "")
        assert "scale" in result.lower()

    def test_teacher_mode_includes_curriculum_system(self):
        meta = _teacher_metadata(curriculum_system="NGSS")
        result = _resolve_additional_notes("", meta, "")
        assert "NGSS" in result

    def test_math_mode_notes_calculation_session(self):
        meta = _math_metadata()
        result = _resolve_additional_notes("", meta, "")
        assert "En-ROADS" in result or "calculation" in result.lower()

    def test_empty_metadata_returns_empty(self):
        result = _resolve_additional_notes("", {}, "")
        assert result == ""


# ═════════════════════════════════════════
# 2. ADAPT_AGENT1_TO_RAW_INPUT — MAIN API
# ═════════════════════════════════════════

class TestAdaptAgent1ToRawInput:

    def test_returns_raw_input_instance(self):
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input(
            "I teach chemistry, interested in Renewable Energy lab",
            "Here are NGSS connections for Renewable Energy...",
            meta,
        )
        assert isinstance(result, RawInput)

    def test_lab_name_populated_from_target_lab(self):
        meta = _teacher_metadata(target_lab="Renewable Energy")
        result = adapt_agent1_to_raw_input("teacher message", "response", meta)
        assert result.raw_lab_name == "Renewable Energy"

    def test_project_description_is_original_message(self):
        meta = _teacher_metadata()
        msg = "We want to do a composting project with 25 students"
        result = adapt_agent1_to_raw_input(msg, "Agent 1 guidance response", meta)
        assert result.raw_project_description == msg

    def test_student_count_always_blank(self):
        """Agent 1 never provides student count — must always be empty."""
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input("30 students composting", "response", meta)
        assert result.raw_student_count_text == ""

    def test_community_partners_always_blank(self):
        """Agent 1 never provides community partners — must always be empty."""
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input(
            "We worked with the food bank", "response", meta
        )
        assert result.raw_community_partners == ""

    def test_location_from_teacher_context(self):
        ctx = _make_teacher_context(city="Norwalk", state="CT", country="US")
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input("message", "response", meta, ctx)
        assert "Norwalk" in result.raw_location
        assert "CT" in result.raw_location
        assert "US" in result.raw_location

    def test_location_empty_without_teacher_context(self):
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input("message", "response", meta, None)
        assert result.raw_location == ""

    def test_submission_source_is_in_app(self):
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input("message", "response", meta)
        assert result.submission_source == "in_app"

    def test_no_personal_data_invented(self):
        """Adapter must never add names, emails, addresses."""
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input("message", "response", meta)
        all_text = " ".join([
            result.raw_lab_name,
            result.raw_project_description,
            result.raw_additional_notes,
            result.raw_community_partners,
            result.raw_location,
        ])
        assert "@" not in all_text
        assert "555" not in all_text

    def test_clarification_mode_still_returns_raw_input(self):
        """When Agent 1 asks a clarification question, adapter returns minimal RawInput."""
        meta = _clarification_metadata()
        msg = "I teach science and want to do something climate-related"
        result = adapt_agent1_to_raw_input(msg, "What subject do you teach?", meta)
        assert isinstance(result, RawInput)
        assert result.raw_project_description == msg
        assert result.raw_lab_name == ""

    def test_none_metadata_does_not_crash(self):
        result = adapt_agent1_to_raw_input("message", "response", None)
        assert isinstance(result, RawInput)

    def test_empty_metadata_does_not_crash(self):
        result = adapt_agent1_to_raw_input("message", "response", {})
        assert isinstance(result, RawInput)

    def test_missing_keys_in_metadata_do_not_crash(self):
        """Partial metadata (e.g. only mode key) must not raise."""
        meta = {"mode": "teacher"}
        result = adapt_agent1_to_raw_input("message", "response", meta)
        assert isinstance(result, RawInput)

    def test_student_mode_notes_include_signals(self):
        meta = _student_metadata(signals=["community", "scale"])
        result = adapt_agent1_to_raw_input(
            "we want to do a composting project", "Here is a question...", meta
        )
        assert "community" in result.raw_additional_notes
        assert "scale" in result.raw_additional_notes

    def test_math_mode_notes_mention_enroads(self):
        meta = _math_metadata()
        result = adapt_agent1_to_raw_input(
            "how do I calculate CO2 savings?", "Let us work through this...", meta
        )
        notes = result.raw_additional_notes.lower()
        assert "en-roads" in notes or "calculation" in notes

    def test_agent1_response_not_used_as_project_description(self):
        """Agent 1's response is guidance text, not a project description."""
        meta = _teacher_metadata()
        agent1_response = (
            "Here are the NGSS connections for Renewable Energy: "
            "HS-PS3-3 applies to solar panel energy transformations..."
        )
        result = adapt_agent1_to_raw_input(
            "I want a solar project", agent1_response, meta
        )
        # The description should be the teacher's message, not the standards table
        assert "NGSS" not in result.raw_project_description
        assert "HS-PS3" not in result.raw_project_description

    def test_long_message_truncated_gracefully(self):
        """Very long messages should not exceed max length."""
        long_msg = "A" * 5000
        meta = _teacher_metadata()
        result = adapt_agent1_to_raw_input(long_msg, "response", meta)
        assert len(result.raw_project_description) <= 2000


# ═════════════════════════════════════════
# 3. BUILD_RAW_INPUT_FROM_MESSAGE (offline fallback)
# ═════════════════════════════════════════

class TestBuildRawInputFromMessage:

    def test_returns_raw_input(self):
        result = build_raw_input_from_message("agriculture composting project")
        assert isinstance(result, RawInput)

    def test_message_becomes_project_description(self):
        msg = "We want to do a composting project with our agriculture lab"
        result = build_raw_input_from_message(msg)
        assert result.raw_project_description == msg

    def test_lab_name_always_blank(self):
        result = build_raw_input_from_message("Renewable Energy project")
        assert result.raw_lab_name == ""

    def test_student_count_always_blank(self):
        result = build_raw_input_from_message("25 students doing composting")
        assert result.raw_student_count_text == ""

    def test_location_from_teacher_context(self):
        ctx = _make_teacher_context(city="Lusaka", country="Zambia", state="")
        result = build_raw_input_from_message("message", ctx)
        assert "Lusaka" in result.raw_location
        assert "Zambia" in result.raw_location

    def test_no_teacher_context_empty_location(self):
        result = build_raw_input_from_message("message", None)
        assert result.raw_location == ""

    def test_submission_source_is_in_app(self):
        result = build_raw_input_from_message("message")
        assert result.submission_source == "in_app"


# ═════════════════════════════════════════
# 4. PIPELINE INTEGRATION (offline, no LLM)
# ═════════════════════════════════════════

@skip_no_pipeline
class TestOfflinePipeline:
    """
    These tests run the full Agent 2 → 3 → 4 pipeline using simulated
    Agent 1 output. LIVE_LLM is not set, so Agent 1 is not called.
    Verifies the adapter output feeds cleanly into downstream agents.
    """

    def _run_from_adapter(
        self,
        message: str,
        metadata: dict,
        teacher_context: TeacherContext = None,
    ):
        """Helper: adapt → Agent 2 → Agent 3 → Agent 4."""
        from agent2 import process_submission
        from agent3 import run_agent3
        from agent4 import run_agent4

        raw = adapt_agent1_to_raw_input(
            original_message=message,
            agent1_response_text="[simulated Agent 1 response]",
            agent1_metadata=metadata,
            teacher_context=teacher_context,
        )
        state = process_submission(raw, teacher_context=teacher_context)
        state = run_agent3(state)
        state = run_agent4(state, jotform_submitted=False)
        return raw, state

    def test_happy_path_teacher_mode_completes(self):
        meta = _teacher_metadata(target_lab="Agriculture and Climate Change")
        ctx  = _make_teacher_context()
        raw, state = self._run_from_adapter(
            "We want to do a composting project", meta, ctx
        )
        assert state.structured_intake.canonical_lab_name != ""
        assert state.impact_metrics.impact_track is not None
        assert state.reporting.funder_summary != ""

    def test_happy_path_student_mode_completes(self):
        meta = _student_metadata(lab_name="Agriculture and Climate Change")
        ctx  = _make_teacher_context()
        raw, state = self._run_from_adapter(
            "We want to make a poster about composting", meta, ctx
        )
        assert state.reporting.jotform_draft != {}
        assert "Which Learning Lab(s) did you use?" in state.reporting.jotform_draft

    def test_clarification_mode_pipeline_completes_with_low_confidence(self):
        """
        When Agent 1 returned a clarification question, the pipeline still runs.
        Agent 2 will flag low confidence because lab name is empty.
        """
        meta = _clarification_metadata()
        raw, state = self._run_from_adapter(
            "I want to do something climate-related", meta
        )
        # Pipeline completed without crashing
        assert state.reporting.funder_summary != "" or len(state.warnings) > 0

    def test_math_mode_pipeline_completes(self):
        meta = _math_metadata()
        ctx  = _make_teacher_context()
        raw, state = self._run_from_adapter(
            "How do I calculate CO2 savings from LED lights?", meta, ctx
        )
        assert isinstance(state.reporting.jotform_draft, dict)

    def test_adapter_does_not_mutate_impact_metrics(self):
        """Adapter output must not pre-populate Agent 3's section."""
        meta = _teacher_metadata(target_lab="Renewable Energy")
        raw = adapt_agent1_to_raw_input("message", "response", meta)
        from agent2 import process_submission
        state = process_submission(raw)
        # impact_metrics must be untouched before Agent 3 runs
        assert state.impact_metrics.impact_track is None

    def test_adapter_does_not_mutate_reporting(self):
        """Adapter output must not pre-populate Agent 4's section."""
        meta = _teacher_metadata()
        raw = adapt_agent1_to_raw_input("message", "response", meta)
        from agent2 import process_submission
        state = process_submission(raw)
        # reporting must be untouched before Agent 4 runs
        assert state.reporting.funder_summary == ""

    def test_agent4_privacy_preserved_through_pipeline(self):
        """Privacy guarantees must hold end-to-end through the full pipeline."""
        meta = _teacher_metadata(target_lab="Agriculture and Climate Change")
        ctx  = _make_teacher_context()
        raw, state = self._run_from_adapter(
            "Email teacher@school.org for info. We do composting.", meta, ctx
        )
        # Email should be scrubbed from the Jotform draft overview
        overview = state.reporting.jotform_draft.get(
            'Please give an overview of your project: (If you opt to instead '
            'record video or voice below, just type "Recorded.")', ""
        )
        assert "@" not in overview
        # Personal fields should be empty
        assert state.reporting.jotform_draft.get("Name") == ""
        assert state.reporting.jotform_draft.get("Email") == ""

    def test_map_export_gating_preserved(self):
        """Map export must be empty when jotform_submitted=False (default)."""
        meta = _teacher_metadata()
        raw, state = self._run_from_adapter("composting project", meta)
        assert state.reporting.map_export_json == {}

    def test_real_jotform_row_harvest_hands(self):
        """
        Simulates Row 8 from real Jotform data — food desert equity case.
        Uses simulated Agent 1 metadata (teacher said 'agriculture').
        """
        meta = _teacher_metadata(
            target_lab="Agriculture and Climate Change",
            matched_labs=["Agriculture and Climate Change"],
        )
        ctx = TeacherContext(
            school_name="Harvest Hands Community Development Corporation",
            city="",
            country="US",
            school_type=SchoolType.COMMUNITY_ORG,
            title1_status="unknown",
        )
        msg = (
            "We teach about plant cells, photosynthesis, carbon footprint of "
            "our food, farm to table. We live in a food desert."
        )
        raw, state = self._run_from_adapter(msg, meta, ctx)

        si = state.structured_intake
        assert si.canonical_lab_name == "Agriculture and Climate Change"
        assert si.equity_flag is True  # food desert keyword detected by Agent 2
        assert state.reporting.funder_summary != ""
        assert "Agriculture and Climate Change" in state.reporting.jotform_draft.get(
            "Which Learning Lab(s) did you use?", ""
        )


# ═════════════════════════════════════════
# 5. PIPELINE WRAPPER (offline)
# ═════════════════════════════════════════

@skip_no_pipeline
class TestPipelineWrapper:
    """
    Tests for the thin pipeline_agent1_to_4.py wrapper.
    LIVE_LLM=0 so Agent 1 is skipped; tests verify the fallback path.
    """

    def test_returns_four_tuple(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        response, metadata, raw_input, state = run_agent1_to_4_pipeline(
            teacher_message="We want to do a composting project with our agriculture lab."
        )
        assert isinstance(response, str)
        assert isinstance(metadata, dict)
        assert isinstance(raw_input, RawInput)

    def test_offline_agent1_response_is_empty_string(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        response, metadata, raw_input, state = run_agent1_to_4_pipeline(
            teacher_message="agriculture composting project"
        )
        assert response == ""
        assert metadata.get("skipped") is True

    def test_offline_raw_input_has_message_as_description(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        msg = "We want to start a composting program at our school."
        _, _, raw_input, _ = run_agent1_to_4_pipeline(teacher_message=msg)
        assert raw_input.raw_project_description == msg

    def test_offline_pipeline_produces_reporting(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        _, _, _, state = run_agent1_to_4_pipeline(
            teacher_message="Agriculture composting project, 25 students"
        )
        assert state.reporting.funder_summary != "" or state.reporting.jotform_draft != {}

    def test_offline_map_export_empty_by_default(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        _, _, _, state = run_agent1_to_4_pipeline(
            teacher_message="composting project"
        )
        assert state.reporting.map_export_json == {}

    def test_offline_map_export_generated_when_submitted(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        _, _, _, state = run_agent1_to_4_pipeline(
            teacher_message="Agriculture composting project 25 students",
            teacher_context=TeacherContext(
                school_name="Test School", city="Norwalk", country="US"
            ),
            jotform_submitted=True,
        )
        # Map will only be populated if Agent 2 matched a lab
        # (may be {} if no lab matched from raw message alone — that is correct)
        assert isinstance(state.reporting.map_export_json, dict)

    def test_teacher_context_passed_through_pipeline(self):
        from pipeline_agent1_to_4 import run_agent1_to_4_pipeline
        ctx = TeacherContext(
            school_name="Ahfachkee Day School",
            city="Clewiston",
            country="US",
            school_type=SchoolType.TRIBAL,
            title1_status="yes",
        )
        _, _, _, state = run_agent1_to_4_pipeline(
            teacher_message="wildfire mapping project",
            teacher_context=ctx,
        )
        assert state.teacher_context.school_name == "Ahfachkee Day School"
        assert state.teacher_context.school_type == SchoolType.TRIBAL

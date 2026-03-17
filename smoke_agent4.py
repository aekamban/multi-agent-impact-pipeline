"""
smoke_agent4.py
TCImpact — End-to-End Pipeline Smoke Test
==========================================

Runs three realistic submissions through the full agent pipeline:
    RawInput → Agent 2 (process_submission)
             → Agent 3 (run_agent3)
             → Agent 4 (run_agent4)

All three submissions are drawn from real TCI Jotform rows.

Usage:
    python smoke_agent4.py              # offline, deterministic only
    LIVE_LLM=1 python smoke_agent4.py  # also exercises LLM paths

What this checks:
    - All four agents chain without errors
    - state.structured_intake populated by Agent 2
    - state.impact_metrics populated by Agent 3
    - state.reporting populated by Agent 4
    - No cross-agent contamination (each agent only writes to its section)
    - Map export gating works correctly
    - Output values are plausible and non-empty
    - Privacy: no PII in generated text

This is a smoke test, not a unit test. It prints a human-readable
summary so you can visually verify outputs before the Kate demo.
"""

import sys
import traceback

from agent2 import process_submission
from agent3 import run_agent3
from agent4 import run_agent4

from project_state import (
    RawInput,
    SchoolLocale,
    SchoolType,
    TeacherContext,
)


# ─────────────────────────────────────────
# COLOUR HELPERS (works on Windows Git Bash)
# ─────────────────────────────────────────

def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


# ─────────────────────────────────────────
# ASSERTION HELPER
# ─────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []

def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    _results.append((label, condition, detail))
    symbol = green("✓") if condition else red("✗")
    detail_str = f"  → {detail}" if detail else ""
    print(f"  {symbol} {label}{detail_str}")
    return condition


# ─────────────────────────────────────────
# SUBMISSION FIXTURES (from real Jotform rows)
# ─────────────────────────────────────────

def _make_enroads_submission():
    """
    Row 3 — Hershey Montessori, En-ROADS lab, 12 students.
    Track A: should produce CO₂ methodology and target assessment.
    """
    raw = RawInput(
        raw_lab_name="Climate Impacts and Solutions with En-ROADS",
        raw_project_description=(
            "The Life Cycle of Stuff: Exploring the environmental impact of the "
            "things we buy. Physical Science (2025-26). Students ran En-ROADS "
            "simulations to model CO₂ reductions from school-wide energy "
            "efficiency improvements and behaviour changes."
        ),
        raw_student_count_text="12",
        raw_additional_notes="Students uploaded work to the book discussion at Lake Erie College.",
        raw_community_partners="Lake Erie College faculty",
        submission_source="jotform_import",
    )
    ctx = TeacherContext(
        school_name="Hershey Montessori School",
        city="Huntsburg",
        state_province="OH",
        country="US",
        school_type=SchoolType.MONTESSORI,
        school_locale=SchoolLocale.RURAL,
        title1_status="no",
    )
    return raw, ctx


def _make_composting_submission():
    """
    Row 5 — Lusaka test (Shilton), Agriculture lab, 65 students.
    Track B: composting project, no equity flag in teacher_context but
    description mentions it's a high school project — good baseline Track B.
    """
    raw = RawInput(
        raw_lab_name="Agriculture and Climate Change",
        raw_project_description="High school composting project",
        raw_student_count_text="65",
        raw_additional_notes=(
            "created and maintained composting systems, "
            "monitored temperatures, observed decomposition, "
            "compared plant growth"
        ),
        raw_community_partners="",
        submission_source="jotform_import",
    )
    ctx = TeacherContext(
        school_name="Lusaka Community School",
        city="Lusaka",
        state_province="",
        country="Zambia",
        school_type=SchoolType.PUBLIC,
        school_locale=SchoolLocale.URBAN,
        title1_status="unknown",
    )
    return raw, ctx


def _make_food_desert_submission():
    """
    Row 8 — Harvest Hands, Agriculture lab, mixed K-8 cohort.
    Track B: garden project with explicit food desert equity signal.
    """
    raw = RawInput(
        raw_lab_name="Agriculture and Climate Change",
        raw_project_description=(
            "We teach about plant cells, photosynthesis, carbon footprint of "
            "our food, farm to table, mycelium, and composting. Students run "
            "a year-round garden that supplies fresh produce to the community."
        ),
        raw_student_count_text="10-25, K-8th",
        raw_additional_notes=(
            "Teaching where food comes from because we live in a food desert. "
            "Our afterschool program serves kids who otherwise have no access "
            "to fresh vegetables."
        ),
        raw_community_partners="Harvest Hands Community Development Corporation",
        submission_source="jotform_import",
    )
    ctx = TeacherContext(
        school_name="Harvest Hands Community Development Corporation",
        city="",
        state_province="",
        country="US",
        school_type=SchoolType.COMMUNITY_ORG,
        school_locale=SchoolLocale.URBAN,
        title1_status="unknown",
    )
    return raw, ctx


# ─────────────────────────────────────────
# PIPELINE RUNNER
# ─────────────────────────────────────────

def run_pipeline(label: str, raw: RawInput, ctx: TeacherContext,
                 jotform_submitted: bool = False):
    print(f"\n{bold('═' * 60)}")
    print(f"{bold(label)}")
    print(bold('═' * 60))

    try:
        # ── Agent 2 ───────────────────────────────────────────────
        print(f"\n{yellow('▶ Agent 2 — Intake & Structuring')}")
        state = process_submission(raw, teacher_context=ctx)

        si = state.structured_intake
        check("Lab matched",
              bool(si.canonical_lab_name),
              si.canonical_lab_name)
        check("Match confidence ≥ 0.80",
              si.lab_match_confidence >= 0.80,
              f"{si.lab_match_confidence:.2f}")
        check("Track assigned",
              si.track is not None,
              str(si.track))
        check("Student count normalised",
              si.num_students_estimate is not None or si.num_students_min is not None,
              f"estimate={si.num_students_estimate}, min={si.num_students_min}, max={si.num_students_max}")
        check("structured_intake written",
              si.canonical_lab_name != "")
        check("Agent 2 left impact_metrics untouched",
              state.impact_metrics.impact_track is None)
        check("Agent 2 left reporting untouched",
              state.reporting.funder_summary == "")

        # ── Agent 3 ───────────────────────────────────────────────
        print(f"\n{yellow('▶ Agent 3 — Impact Calculator')}")
        state = run_agent3(state)

        im = state.impact_metrics
        check("impact_track set",
              im.impact_track is not None,
              str(im.impact_track))
        check("methodology_notes non-empty",
              bool(im.methodology_notes),
              im.methodology_notes[:80])

        if str(im.impact_track) in ("Track.A", "A"):
            check("Track A: co2_reduction_methodology populated",
                  bool(im.co2_reduction_methodology))
            check("Track A: epa_emissions_factor_used populated",
                  bool(im.epa_emissions_factor_used))
        else:
            check("Track B: reach_estimate set",
                  im.reach_estimate is not None,
                  str(im.reach_estimate))
            check("Track B: community_score_total set",
                  im.community_score_total is not None,
                  str(im.community_score_total))
            check("Track B: behavior_change_proxy non-empty",
                  bool(im.behavior_change_proxy),
                  im.behavior_change_proxy[:60])

        check("Agent 3 left structured_intake untouched",
              si.canonical_lab_name == state.structured_intake.canonical_lab_name)
        check("Agent 3 left reporting untouched",
              state.reporting.funder_summary == "")

        # ── Agent 4 ───────────────────────────────────────────────
        print(f"\n{yellow('▶ Agent 4 — Funder Summary & Reporting')}")
        state = run_agent4(state, jotform_submitted=jotform_submitted)

        rp = state.reporting
        lm = rp.logic_model

        check("logic_model populated",
              len(lm.inputs) > 0 and len(lm.activities) > 0)
        check("logic_model_text non-empty",
              bool(rp.logic_model_text),
              rp.logic_model_text[:80])
        check("funder_summary non-empty",
              bool(rp.funder_summary),
              rp.funder_summary[:100])
        check("jotform_draft has real Jotform header",
              "Which Learning Lab(s) did you use?" in rp.jotform_draft)
        check("jotform_draft lab field populated",
              bool(rp.jotform_draft.get("Which Learning Lab(s) did you use?")),
              rp.jotform_draft.get("Which Learning Lab(s) did you use?"))
        check("jotform_draft overview non-empty",
              bool(rp.jotform_draft.get(
                  'Please give an overview of your project: (If you opt to instead '
                  'record video or voice below, just type "Recorded.")'
              )))
        check("jotform_draft Name field is empty string (privacy)",
              rp.jotform_draft.get("Name") == "")
        check("jotform_draft Email field is empty string (privacy)",
              rp.jotform_draft.get("Email") == "")
        check("jotform_draft has _privacy_note",
              "_privacy_note" in rp.jotform_draft)
        check("jotform_draft has _blank_fields list",
              isinstance(rp.jotform_draft.get("_blank_fields"), list))

        # Map export gating
        if jotform_submitted:
            check("map_export_json populated (submitted=True)",
                  bool(rp.map_export_json),
                  f"keys: {list(rp.map_export_json.keys())[:6]}")
            check("map_export lab_name present",
                  bool(rp.map_export_json.get("lab_name")))
            check("map_export lat/lng are None placeholders",
                  rp.map_export_json.get("lat") is None
                  and rp.map_export_json.get("lng") is None)
            check("map_export no email/phone",
                  "email" not in rp.map_export_json
                  and "phone" not in rp.map_export_json)
        else:
            check("map_export_json empty (submitted=False)",
                  rp.map_export_json == {})

        check("Agent 4 left structured_intake untouched",
              state.structured_intake.canonical_lab_name == si.canonical_lab_name)
        check("Agent 4 left impact_metrics untouched",
              state.impact_metrics.impact_track == im.impact_track)

        # Privacy spot-check: no raw email-like patterns in generated text
        generated = rp.funder_summary + rp.logic_model_text
        check("No email addresses in generated text",
              "@" not in generated)

        print(f"\n{green('Pipeline completed successfully.')}")
        return True

    except Exception as e:
        print(f"\n{red('PIPELINE EXCEPTION:')}")
        traceback.print_exc()
        return False


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    print(bold("\nTCImpact — End-to-End Pipeline Smoke Test"))
    print(bold("Agents: 2 → 3 → 4  |  Real Jotform data\n"))

    scenarios = [
        (
            "Scenario 1 — Track A: En-ROADS (Hershey Montessori, OH)",
            *_make_enroads_submission(),
            False,   # jotform_submitted
        ),
        (
            "Scenario 2 — Track B: Composting (Lusaka, Zambia) — map gated",
            *_make_composting_submission(),
            False,
        ),
        (
            "Scenario 3 — Track B: Food desert garden (Harvest Hands) — map published",
            *_make_food_desert_submission(),
            True,    # jotform_submitted — exercises map export
        ),
    ]

    pipeline_results = []
    for label, raw, ctx, submitted in scenarios:
        ok = run_pipeline(label, raw, ctx, jotform_submitted=submitted)
        pipeline_results.append(ok)

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{bold('═' * 60)}")
    print(bold("SMOKE TEST SUMMARY"))
    print(bold('═' * 60))

    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed
    pipe_ok = all(pipeline_results)

    for label, ok, detail in _results:
        symbol = green("✓") if ok else red("✗")
        print(f"  {symbol} {label}")

    print()
    if failed == 0 and pipe_ok:
        print(green(f"ALL CHECKS PASSED  ({passed}/{total})"))
        print(green("Full pipeline: Agent 2 → 3 → 4 is working end-to-end."))
        sys.exit(0)
    else:
        print(red(f"FAILURES: {failed}/{total} checks failed"))
        if not pipe_ok:
            print(red("One or more pipelines raised an exception — see above."))
        sys.exit(1)


if __name__ == "__main__":
    main()

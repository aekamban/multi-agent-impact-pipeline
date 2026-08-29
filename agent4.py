"""
agent4.py
TCImpact — Agent 4: Community Impact & Funder Summary
======================================================

Reads:
    state.structured_intake  (StructuredIntake, written by Agent 2)
    state.impact_metrics     (ImpactMetrics, written by Agent 3)
    state.raw_input          (RawInput — project description, location)
    state.teacher_context    (TeacherContext — school, city, country)

Writes (only to state.reporting):
    state.reporting.logic_model        LogicModel object
    state.reporting.logic_model_text   Plain-text rendering
    state.reporting.jotform_draft      dict keyed by real Jotform headers
    state.reporting.funder_summary     Grant-ready narrative paragraph
    state.reporting.map_export_json    Moore Foundation format dict (gated)

Design rules:
    - No LLM calls by default. All outputs are deterministic.
    - funder_summary LLM upgrade is gated behind LIVE_LLM=1 with a
      deterministic fallback that always works.
    - Never touches state.structured_intake, state.impact_metrics,
      agent2.py, agent3.py, project_state.py, or database.py.
    - Safe to re-run at any point in the year — overwrites, never appends.
    - map_export_json is gated on jotform_submitted=True to avoid
      publishing incomplete or unconfirmed projects to the Moore Foundation
      map backend.

Privacy / data minimization:
    - Agent 4 does NOT generate, store, or fabricate:
        student names, mailing addresses, photos/videos, upload URLs,
        or consent fields.
    - These are left blank in jotform_draft with an explanatory note.
    - Teacher is the source of truth: teacher_context and structured_intake
      are preferred over raw_input for all structured fields.
    - Student counts > 10,000 are treated as data-entry errors and replaced
      with None. Nonsensical text inputs are replaced with "".

Iterative / year-round behavior:
    - run_agent4() can be called at any phase: planning, implementing, or
      analyzing. Outputs improve as more data is available.
    - Each call fully recomputes and overwrites all reporting fields.
      There is no accumulation across calls.
    - map_export_json is {} until jotform_submitted=True, so partial records
      are never published prematurely.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any, Optional

from project_state import (
    ImpactMetrics,
    LogicModel,
    ProjectState,
    Reporting,
    StructuredIntake,
    TeacherContext,
    Track,
)

# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

# Real Jotform column headers from TCI export (exact strings).
# Sensitive / media / consent fields are intentionally left blank —
# see JOTFORM_BLANK_NOTE below.
JF_SUBMISSION_DATE = "Submission Date"
JF_NAME            = "Name"
JF_EMAIL           = "Email"
JF_PHONE           = "Phone Number"
JF_SCHOOL          = "Name of your school or institution:"
JF_STUDENT_COUNT   = "How many students completed your Action Project?"
JF_LAB             = "Which Learning Lab(s) did you use?"
JF_TOPIC           = "Which best captures your project's thematic topic?"
JF_OVERVIEW        = (
    'Please give an overview of your project: (If you opt to instead record '
    'video or voice below, just type "Recorded.")'
)
JF_VIDEO_OVERVIEW  = (
    'If you or your students would like to respond to the previous question '
    'by video recording, use this tool: (Click "camera only")'
)
JF_VOICE_OVERVIEW  = (
    "If you'd prefer to answer the previous question by voice recording, "
    "use this tool: "
)
JF_HIGHLIGHTS      = (
    "Please provide any highlights or student feedback from the project, "
    "including student quotes, reactions, challenges, or successes. "
    '(If you opt to instead record video or voice below, just type "Recorded.")'
)
JF_VIDEO_HIGHLIGHTS = (
    'If you or your students would like to respond to the previous question '
    'by video recording, use this tool: (Click "camera only")'
)
JF_VOICE_HIGHLIGHTS = (
    "If you'd prefer to answer the previous question by voice recording, "
    "use this tool: "
)
JF_UPLOAD          = (
    "Please upload any supporting documents or evidence of your Action Project "
    "(videos, photos, slides, lesson plans, or other materials), in order to "
    "inspire other educators:"
)
JF_MERCH_CONSENT   = (
    "We deeply appreciate your collaboration and unwavering support for our "
    "organization over the years. As a token of our gratitude, we are excited "
    "to offer a $50 gift card to all participants that will be sent to you "
    "digitally at the email address you provided. Additionally, to recognize "
    "the most thorough and detailed responses to this form, we'd like to send "
    "free TCI merchandise as a thank-you! If you'd like to be considered, "
    "kindly provide your address."
)
JF_MAILING_ADDRESS = "Mailing address, for shipping your free TCI merch:"
JF_CONSENT         = (
    "By submitting this form, you agree that TCI can use this material for "
    "promotion, marketing, and dissemination."
)

# Privacy metadata key added to jotform_draft (machine-readable by the UI).
# Personal-data fields are left as "" — this note explains why and lists them.
JOTFORM_PRIVACY_NOTE = (
    "This draft was generated by TCImpact. "
    "Sensitive personal data (name, email, phone, address), student media, "
    "upload evidence, and consent must be completed directly in TCI's official "
    "Jotform for privacy compliance. This system does not collect or store them."
)

# Keys of personal-data / media / consent fields intentionally left blank.
# Stored in _blank_fields so the UI can display a targeted guidance banner.
JOTFORM_BLANK_FIELDS = [
    "Name",
    "Email",
    "Phone Number",
    "Please upload any supporting documents or evidence of your Action Project "
    "(videos, photos, slides, lesson plans, or other materials), in order to "
    "inspire other educators:",
    "We deeply appreciate your collaboration and unwavering support for our "
    "organization over the years. As a token of our gratitude, we are excited "
    "to offer a $50 gift card to all participants that will be sent to you "
    "digitally at the email address you provided. Additionally, to recognize "
    "the most thorough and detailed responses to this form, we'd like to send "
    "free TCI merchandise as a thank-you! If you'd like to be considered, "
    "kindly provide your address.",
    "Mailing address, for shipping your free TCI merch:",
    "By submitting this form, you agree that TCI can use this material for "
    "promotion, marketing, and dissemination.",
]

# Student count sanity cap.
# Counts above this threshold are treated as data-entry errors.
MAX_REALISTIC_STUDENT_COUNT = 10_000

# Minimum character length for a narrative field to be considered substantive.
# Inputs shorter than this (after stripping) are treated as insufficient signal.
_MIN_NARRATIVE_LEN = 3


# ─────────────────────────────────────────
# INPUT HELPERS
# ─────────────────────────────────────────

def _safe_str(value: Any, max_len: int = 2000) -> str:
    """
    Coerce value to a clean string.
    Returns "" for None, non-string types that can't be converted, or
    strings that are whitespace-only. Truncates at max_len.
    """
    if value is None:
        return ""
    try:
        s = str(value).strip()
    except Exception:
        return ""
    return s[:max_len]


def _safe_student_count(value: Any) -> Optional[int]:
    """
    Return a validated student count integer, or None if the value is missing,
    non-numeric, zero, or unrealistically large (> MAX_REALISTIC_STUDENT_COUNT).
    Teacher is the source of truth — this guard only catches obvious data errors.
    """
    if value is None:
        return None
    try:
        n = int(float(str(value).replace(",", "")))
    except (ValueError, TypeError):
        return None
    if n <= 0 or n > MAX_REALISTIC_STUDENT_COUNT:
        return None
    return n


def _intake_dict(structured_intake: Any) -> dict:
    """Normalize StructuredIntake to a plain dict (mirrors Agent 3 pattern)."""
    if structured_intake is None:
        return {}
    if isinstance(structured_intake, dict):
        return structured_intake
    if hasattr(structured_intake, "model_dump"):
        return structured_intake.model_dump()
    if hasattr(structured_intake, "__dict__"):
        return vars(structured_intake)
    return {}


def _metrics_dict(impact_metrics: Any) -> dict:
    """Normalize ImpactMetrics to a plain dict."""
    if impact_metrics is None:
        return {}
    if isinstance(impact_metrics, dict):
        return impact_metrics
    if hasattr(impact_metrics, "model_dump"):
        return impact_metrics.model_dump()
    if hasattr(impact_metrics, "__dict__"):
        return vars(impact_metrics)
    return {}


def _best_student_count(intake: dict) -> Optional[int]:
    """
    Return the best available validated student count from intake.
    Priority: num_students_estimate → num_students_max → num_students_min.
    """
    for field in ("num_students_estimate", "num_students_max", "num_students_min"):
        val = _safe_student_count(intake.get(field))
        if val is not None:
            return val
    return None


def _is_title1(teacher_context: Optional[TeacherContext]) -> bool:
    """
    Normalise title1_status to a boolean, handling all reasonable variants.
    Truthy: "yes", "Yes", "YES", True, 1
    All other values (None, "no", "unknown", False, 0) return False.
    Mirrors the pattern used in Agent 2 (_is_title1) for consistency.
    """
    if teacher_context is None:
        return False
    raw = getattr(teacher_context, "title1_status", None)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw == 1
    if isinstance(raw, str):
        return raw.strip().lower() == "yes"
    return False


# Compiled PII patterns for _scrub_pii().
# Applied only to teacher-authored free text (raw_project_description,
# raw_additional_notes) — NOT to structured fields we generated ourselves.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Email addresses
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b'), "[email removed]"),
    # Phone numbers — US and international patterns
    (re.compile(r'\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b'), "[phone removed]"),
    (re.compile(r'\+\d{1,3}[\s.\-]?\(?\d+\)?[\s.\-]?\d+[\s.\-]?\d+'), "[phone removed]"),
    # URLs
    (re.compile(r'https?://\S+'), "[link removed]"),
    (re.compile(r'www\.\S+\.\S+'), "[link removed]"),
    # Street address patterns: "123 Main St", "456 Oak Avenue"
    (re.compile(
        r'\b\d{1,5}\s+[A-Za-z0-9\s]{2,30}\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|'
        r'Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place)\b',
        re.IGNORECASE,
    ), "[address removed]"),
]


def _scrub_pii(text: str) -> str:
    """
    Apply lightweight deterministic PII redaction to teacher-authored free text.
    Removes email addresses, phone numbers, URLs, and obvious street addresses.
    Returns the scrubbed string. Safe to call on empty strings.

    Scope: call this only on raw_input fields (teacher free text).
    Do NOT call on structured fields generated by Agent 4 itself.
    """
    if not text:
        return text
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_nonsense(text: str) -> bool:
    """
    Return True if a narrative string is clearly too short or obviously invalid
    to be used as project content.

    Heuristics (all deterministic):
      - Blank / whitespace only
      - Shorter than _MIN_NARRATIVE_LEN characters
      - Consists entirely of repeated characters (e.g. "aaaaaaa", "??????")
      - Consists entirely of non-alphanumeric characters

    Returns False (i.e. text is acceptable) in all other cases.
    The bar is intentionally low — we only catch obvious junk, not poor quality.
    """
    stripped = text.strip() if text else ""
    if not stripped or len(stripped) < _MIN_NARRATIVE_LEN:
        return True
    # All identical characters
    if len(set(stripped)) == 1:
        return True
    # No alphanumeric content at all
    if not re.search(r'[a-zA-Z0-9]', stripped):
        return True
    return False


# ─────────────────────────────────────────
# A. LOGIC MODEL GENERATION
# ─────────────────────────────────────────

# Logic model content keyed by project_type.
# Each entry provides typical INPUTS, ACTIVITIES, OUTPUTS, SHORT-TERM OUTCOMES,
# and INTERMEDIATE OUTCOMES that a TCI teacher would recognise as accurate.
# Agent 4 assembles these into a LogicModel and enriches with live state values.

_LOGIC_MODEL_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "Composting program": {
        "activities":           ["Set up composting systems", "Monitor decomposition", "Track diversion of organic waste"],
        "outputs":              ["Operational compost bin or system", "Compost applied to school garden or grounds"],
        "short_term_outcomes":  ["Students understand food-waste cycles", "Measurable reduction in cafeteria waste"],
        "intermediate_outcomes":["Composting behaviour adopted by school community", "Reduced landfill contribution"],
    },
    "Renewable energy installation": {
        "activities":           ["Assess school energy use", "Install or advocate for solar/wind infrastructure", "Monitor energy production"],
        "outputs":              ["Renewable energy system installed or scoped", "Energy audit report"],
        "short_term_outcomes":  ["Measurable reduction in grid electricity consumption", "Students can calculate CO₂ savings"],
        "intermediate_outcomes":["Long-term energy cost savings for school", "Replicable model for peer schools"],
    },
    "Tree planting / reforestation": {
        "activities":           ["Identify planting sites", "Source native seedlings", "Plant and maintain trees"],
        "outputs":              ["Trees planted in school or community grounds"],
        "short_term_outcomes":  ["Increased green coverage", "Students learn sequestration science"],
        "intermediate_outcomes":["Annual CO₂ sequestration documented", "Habitat created or restored"],
    },
    "Food waste reduction": {
        "activities":           ["Audit cafeteria waste", "Launch waste-reduction campaign", "Track weekly diversion"],
        "outputs":              ["Waste audit data", "Cafeteria policy change proposal"],
        "short_term_outcomes":  ["Reduction in food waste measured", "Student and staff behaviour shift"],
        "intermediate_outcomes":["Sustained waste-reduction practices", "Model for district-wide adoption"],
    },
    "Recycling program": {
        "activities":           ["Audit current recycling rates", "Set up sorting stations", "Educate peers"],
        "outputs":              ["Recycling stations deployed", "Diversion rate baseline established"],
        "short_term_outcomes":  ["Increased recycling rates in school", "Peer behaviour change"],
        "intermediate_outcomes":["Institutionalised recycling practice", "Waste-diversion data shared with district"],
    },
    "School/community garden": {
        "activities":           ["Design and build garden beds", "Plant and tend crops", "Connect produce to school meals or food bank"],
        "outputs":              ["Active garden space producing food", "Students with hands-on growing experience"],
        "short_term_outcomes":  ["Students understand food systems and seasonality", "Community food access improved"],
        "intermediate_outcomes":["Sustained garden maintained by school", "Food-justice awareness embedded in curriculum"],
    },
    "Policy advocacy / letter writing": {
        "activities":           ["Research local climate policy", "Draft and submit letters or petitions", "Present to decision-makers"],
        "outputs":              ["Letters or petitions submitted to officials", "Students engaged in civic process"],
        "short_term_outcomes":  ["Decision-makers aware of student climate concerns", "Students develop civic agency"],
        "intermediate_outcomes":["Policy change influenced or documented", "Replicable civic engagement model"],
    },
    "Awareness / communications campaign": {
        "activities":           ["Research climate topic", "Design campaign materials", "Share with school or community audience"],
        "outputs":              ["Campaign materials created (posters, social media, presentations)", "Audience reached"],
        "short_term_outcomes":  ["Increased awareness of climate issue in target audience", "Students develop communication skills"],
        "intermediate_outcomes":["Community conversations sparked", "Campaign adopted or extended by school"],
    },
    "Habitat restoration / invasive species removal": {
        "activities":           ["Map invasive species or degraded habitat", "Remove invasives", "Plant native species"],
        "outputs":              ["Area cleared and replanted", "Habitat monitoring plan in place"],
        "short_term_outcomes":  ["Native biodiversity increased in restoration area", "Students develop ecological literacy"],
        "intermediate_outcomes":["Self-sustaining restored habitat", "Data contributed to citizen science networks"],
    },
    "Environmental trail / outdoor classroom": {
        "activities":           ["Design trail or outdoor learning space", "Install interpretive signage", "Lead peer or community tours"],
        "outputs":              ["Accessible outdoor learning environment created"],
        "short_term_outcomes":  ["Students and community members engaged outdoors", "Environmental literacy increased"],
        "intermediate_outcomes":["Permanent learning resource for school community", "Inspires further outdoor education"],
    },
    "Nature journaling / citizen science": {
        "activities":           ["Conduct regular outdoor observations", "Record and submit data to citizen science platform", "Analyse findings"],
        "outputs":              ["Observation records and data submitted", "Student scientific portfolios"],
        "short_term_outcomes":  ["Students develop scientific observation skills", "Local biodiversity documented"],
        "intermediate_outcomes":["Data contributes to regional or national citizen science database", "Ongoing monitoring established"],
    },
    "Youth engagement / club": {
        "activities":           ["Launch and run environmental club", "Organise events and campaigns", "Recruit and mentor peers"],
        "outputs":              ["Active student-led club or group", "Events and campaigns delivered"],
        "short_term_outcomes":  ["Peer leadership and environmental agency developed", "Wider student body engaged"],
        "intermediate_outcomes":["Self-sustaining student-led organisation", "Alumni continue work post-graduation"],
    },
    "Curriculum integration / life cycle analysis": {
        "activities":           ["Conduct life cycle analysis of product or system", "Present findings to class or school", "Connect to curriculum standards"],
        "outputs":              ["Life cycle analysis report or presentation", "Curriculum unit documented"],
        "short_term_outcomes":  ["Students apply systems thinking to real products", "Curriculum meaningfully integrates climate content"],
        "intermediate_outcomes":["Curriculum unit shared with department or district", "Replicable model for other teachers"],
    },
    "Transportation behavior change": {
        "activities":           ["Audit school commute patterns", "Launch walking / cycling / carpooling campaign", "Track mode shifts"],
        "outputs":              ["Commute audit data", "Campaign materials and results"],
        "short_term_outcomes":  ["Measurable shift to lower-carbon commute modes", "Students calculate emissions savings"],
        "intermediate_outcomes":["School travel plan updated", "CO₂ savings documented for funder reporting"],
    },
    "Energy reduction/efficiency": {
        "activities":           ["Conduct energy audit", "Identify and implement efficiency measures", "Monitor savings"],
        "outputs":              ["Energy audit report", "Efficiency measures installed or recommended"],
        "short_term_outcomes":  ["Measurable reduction in energy consumption", "Students learn energy literacy"],
        "intermediate_outcomes":["Cost and carbon savings documented", "Findings shared with facilities team"],
    },
}

_LOGIC_MODEL_DEFAULT = {
    "activities":           ["Research local climate issue", "Design and implement action project", "Document and share outcomes"],
    "outputs":              ["Action project completed", "Findings shared with school community"],
    "short_term_outcomes":  ["Students develop climate agency and project skills", "Community awareness raised"],
    "intermediate_outcomes":["Replicable project model documented", "Students equipped for future climate action"],
}

# Track A (En-ROADS) has a distinct logic model focused on carbon calculations.
_LOGIC_MODEL_TRACK_A = {
    "activities":           ["Run En-ROADS climate model simulations", "Calculate CO₂ reductions from proposed changes", "Present findings to school or community"],
    "outputs":              ["En-ROADS scenario analysis completed", "CO₂ reduction estimate calculated using EPA emissions factors"],
    "short_term_outcomes":  ["Students understand levers of climate change at systems level", "Concrete CO₂ target progress demonstrated"],
    "intermediate_outcomes":["Students equipped to communicate evidence-based climate solutions", "Data contributes to school or community climate planning"],
}


def build_logic_model(
    intake: dict,
    metrics: dict,
    teacher_context: Optional[TeacherContext] = None,
) -> LogicModel:
    """
    Build a LogicModel deterministically from structured_intake and impact_metrics.

    Inputs are drawn from:
      - project_type → selects template activities, outputs, outcomes
      - track         → Track A uses En-ROADS-specific template
      - num_students_estimate, reach_estimate → populates inputs
      - community_partnerships → enriches inputs and outputs
      - sustained_action, equity_flag, co2_reduction_lbs → enrich outcomes
      - policy_influence_flag / policy_description → enrich intermediate outcomes

    All fields are strings; none contain personally identifying information.
    """
    track_val = intake.get("track")
    is_track_a = (track_val == Track.A or track_val == "A")

    project_type = _safe_str(intake.get("project_type")) or "Other"
    lab_name     = _safe_str(intake.get("canonical_lab_name")) or "TCI Learning Lab"
    thematic     = _safe_str(intake.get("thematic_topic"))

    student_count = _best_student_count(intake) or _safe_student_count(metrics.get("reach_estimate"))

    # Build INPUTS
    inputs: list[str] = [f"TCI {lab_name} curriculum"]
    if student_count:
        inputs.append(f"{student_count:,} students")

    # Duration from intake if present
    duration = intake.get("project_duration_weeks")
    if duration:
        try:
            inputs.append(f"{int(duration)}-week project")
        except (ValueError, TypeError):
            pass

    # Community partnerships as inputs
    partners_raw = intake.get("community_partnerships") or []
    partner_names: list[str] = []
    if isinstance(partners_raw, list):
        for p in partners_raw:
            if isinstance(p, dict):
                name = _safe_str(p.get("name"))
            elif hasattr(p, "name"):
                name = _safe_str(getattr(p, "name", ""))
            else:
                name = ""
            if name:
                partner_names.append(name)
    if partner_names:
        inputs.append(f"Community partners: {', '.join(partner_names[:3])}")
    elif metrics.get("partnership_count", 0):
        inputs.append(f"{metrics['partnership_count']} community partner(s)")

    if thematic:
        inputs.append(f"Thematic focus: {thematic}")

    # Select template
    if is_track_a:
        template = _LOGIC_MODEL_TRACK_A
    else:
        template = _LOGIC_MODEL_TEMPLATES.get(project_type, _LOGIC_MODEL_DEFAULT)

    activities           = list(template["activities"])
    outputs              = list(template["outputs"])
    short_term_outcomes  = list(template["short_term_outcomes"])
    intermediate_outcomes = list(template["intermediate_outcomes"])

    # Enrich outputs with CO₂ figure (Track A)
    co2_lbs = metrics.get("co2_reduction_lbs")
    if is_track_a and co2_lbs:
        try:
            outputs.append(f"Estimated CO₂ reduction: {float(co2_lbs):,.0f} lbs CO₂e")
        except (ValueError, TypeError):
            pass

    # Enrich short-term outcomes with reach
    if student_count and not is_track_a:
        short_term_outcomes.append(f"{student_count:,} students directly engaged")

    # Enrich intermediate outcomes with sustained action
    sustained = intake.get("sustained_action")
    if sustained is True:
        intermediate_outcomes.append("Project continues beyond the class period — lasting community impact")

    # Enrich intermediate outcomes with policy outcome
    policy_flag = metrics.get("policy_influence_flag")
    policy_desc = _safe_str(metrics.get("policy_description"))
    if policy_flag and policy_desc:
        intermediate_outcomes.append(f"Policy outcome: {policy_desc}")
    elif policy_flag:
        intermediate_outcomes.append("Policy or advocacy outcome documented")

    # Build equity note (no personal data)
    equity_note = ""
    equity = intake.get("equity_flag")
    if equity is True or _is_title1(teacher_context):
        equity_note = (
            "Project serves an underserved or Title I community — "
            "equity dimension reflected in community impact scoring."
        )

    return LogicModel(
        inputs=inputs,
        activities=activities,
        outputs=outputs,
        short_term_outcomes=short_term_outcomes,
        intermediate_outcomes=intermediate_outcomes,
        equity_note=equity_note,
    )


# ─────────────────────────────────────────
# B. JOTFORM DRAFT GENERATION
# ─────────────────────────────────────────

def build_jotform_draft(
    intake: dict,
    metrics: dict,
    raw_input: Any,
    teacher_context: Optional[TeacherContext] = None,
) -> dict[str, str]:
    """
    Build a draft dict keyed by the real TCI Jotform column headers.

    Design principles:
      - Teacher is the source of truth. Prefer teacher_context and
        structured_intake over raw_input for all structured fields.
      - Personal-data fields (name, email, phone, address, upload, consent)
        are left as empty strings "". They are never filled by this system.
        A machine-readable _privacy_note and _blank_fields list explain this.
      - Free-text fields from raw_input are PII-scrubbed before inclusion.
      - Nonsense / boundary-testing inputs are replaced with a structured
        deterministic fallback rather than echoed verbatim.
      - Media / upload fields remain blank — project artifacts are described
        as "to be submitted via TCI's official form", never implied to be
        stored here.
      - The draft is a starting point for the teacher to review and complete.
    """
    today = date.today().strftime("%b %d, %Y")

    # Student count — validated
    student_count = _best_student_count(intake)
    student_count_str = f"{student_count:,}" if student_count else ""

    lab_name  = _safe_str(intake.get("canonical_lab_name"))
    thematic  = _safe_str(intake.get("thematic_topic"))
    school    = ""
    if teacher_context:
        school = _safe_str(getattr(teacher_context, "school_name", ""))

    # Project overview — from raw_input.raw_project_description (teacher-authored).
    # Apply PII scrub and nonsense guard before including.
    overview = ""
    if raw_input:
        raw_desc = _safe_str(getattr(raw_input, "raw_project_description", ""))
        if not _is_nonsense(raw_desc):
            overview = _scrub_pii(raw_desc)
    if not overview:
        # Structured fallback when raw description is absent or invalid
        parts = []
        if lab_name:
            parts.append(f"TCI {lab_name} action project.")
        if thematic:
            parts.append(f"Thematic focus: {thematic}.")
        if student_count:
            parts.append(f"{student_count:,} students participated.")
        overview = " ".join(parts) if parts else ""

    # Highlights — build from metrics + notes.
    # Apply PII scrub and nonsense guard to any teacher-authored notes.
    highlights_parts: list[str] = []

    if raw_input:
        notes = _safe_str(getattr(raw_input, "raw_additional_notes", ""))
        if notes and not _is_nonsense(notes):
            highlights_parts.append(_scrub_pii(notes))

    reach = metrics.get("reach_estimate")
    if reach:
        try:
            highlights_parts.append(f"Estimated reach: {int(reach):,} people.")
        except (ValueError, TypeError):
            pass

    partner_count = metrics.get("partnership_count", 0)
    if partner_count:
        highlights_parts.append(
            f"Community partnerships: {partner_count} partner(s) engaged."
        )

    behavior = _safe_str(metrics.get("behavior_change_proxy"))
    if behavior:
        highlights_parts.append(f"Behavior change assessment: {behavior}.")

    co2_lbs = metrics.get("co2_reduction_lbs")
    if co2_lbs:
        try:
            highlights_parts.append(
                f"Estimated CO₂ reduction: {float(co2_lbs):,.0f} lbs CO₂e "
                f"(calculated using EPA emissions factors)."
            )
        except (ValueError, TypeError):
            pass

    policy_flag = metrics.get("policy_influence_flag")
    policy_desc = _safe_str(metrics.get("policy_description"))
    if policy_flag and policy_desc:
        highlights_parts.append(f"Policy outcome: {policy_desc}.")
    elif policy_flag:
        highlights_parts.append("Policy or advocacy outcome documented.")

    highlights_parts.append(
        "Note: project artifacts (photos, videos, slides) are to be submitted "
        "via TCI's official Jotform — they are not stored in this system."
    )

    highlights = " ".join(highlights_parts)

    return {
        # ── Fillable fields ───────────────────────────────────────
        JF_SUBMISSION_DATE:  today,
        JF_NAME:             "",   # personal data — see _privacy_note
        JF_EMAIL:            "",   # personal data — see _privacy_note
        JF_PHONE:            "",   # personal data — see _privacy_note
        JF_SCHOOL:           school,
        JF_STUDENT_COUNT:    student_count_str,
        JF_LAB:              lab_name,
        JF_TOPIC:            thematic,
        JF_OVERVIEW:         overview,
        JF_VIDEO_OVERVIEW:   "",
        JF_VOICE_OVERVIEW:   "",
        JF_HIGHLIGHTS:       highlights,
        JF_VIDEO_HIGHLIGHTS: "",
        JF_VOICE_HIGHLIGHTS: "",
        JF_UPLOAD:           "",   # media — see _privacy_note
        JF_MERCH_CONSENT:    "",   # personal data — see _privacy_note
        JF_MAILING_ADDRESS:  "",   # personal data — see _privacy_note
        JF_CONSENT:          "",   # consent — see _privacy_note
        # ── Privacy metadata (machine-readable) ───────────────────
        # UI should display _privacy_note as a guidance banner and
        # highlight _blank_fields as requiring teacher input.
        "_privacy_note":     JOTFORM_PRIVACY_NOTE,
        "_blank_fields":     JOTFORM_BLANK_FIELDS,
    }


# ─────────────────────────────────────────
# C. FUNDER SUMMARY GENERATION
# ─────────────────────────────────────────

def build_funder_summary_deterministic(
    intake: dict,
    metrics: dict,
    teacher_context: Optional[TeacherContext] = None,
) -> str:
    """
    Build a grant-ready funder summary paragraph using deterministic templating.
    This is always the default. The LLM upgrade path (LIVE_LLM=1) calls this
    first and passes the result as a seed to the LLM for fluency improvement.

    Output is a single cohesive paragraph suitable for a grant report.
    No personal data (names, addresses) is included.
    """
    lab_name      = _safe_str(intake.get("canonical_lab_name")) or "a TCI Learning Lab"
    project_type  = _safe_str(intake.get("project_type")) or "an action project"
    thematic      = _safe_str(intake.get("thematic_topic"))
    track_val     = intake.get("track")
    is_track_a    = (track_val == Track.A or track_val == "A")

    student_count = _best_student_count(intake) or _safe_student_count(metrics.get("reach_estimate"))
    student_str   = f"{student_count:,} students" if student_count else "a group of students"

    school = ""
    city   = ""
    country = ""
    if teacher_context:
        school  = _safe_str(getattr(teacher_context, "school_name", ""))
        city    = _safe_str(getattr(teacher_context, "city", ""))
        country = _safe_str(getattr(teacher_context, "country", ""))

    location_parts = [p for p in [city, country] if p]
    location_str   = f" in {', '.join(location_parts)}" if location_parts else ""
    school_str     = f" at {school}" if school else ""

    # Lead sentence
    summary_parts = [
        f"{student_str}{school_str}{location_str} implemented {project_type} "
        f"as part of TCI's {lab_name} curriculum."
    ]

    # Thematic context
    if thematic:
        summary_parts.append(f"The project addressed the theme of {thematic.lower()}.")

    # Track A: carbon outcomes
    co2_lbs = metrics.get("co2_reduction_lbs")
    target_met = metrics.get("co2_target_met")
    if is_track_a and co2_lbs:
        try:
            target_clause = (
                "meeting the 10,000 lb class target"
                if target_met
                else "contributing toward the 10,000 lb class target"
            )
            summary_parts.append(
                f"Using EPA-standard emissions factors, students calculated an estimated "
                f"CO₂ reduction of {float(co2_lbs):,.0f} lbs CO₂e, {target_clause}."
            )
        except (ValueError, TypeError):
            pass

    # Track B: community outcomes
    if not is_track_a:
        partner_count = metrics.get("partnership_count", 0)
        if partner_count:
            summary_parts.append(
                f"The project engaged {partner_count} community partner(s), "
                f"extending impact beyond the classroom."
            )

        behavior = _safe_str(metrics.get("behavior_change_proxy"))
        if behavior:
            summary_parts.append(f"Behavior change assessment: {behavior}.")

        community_total = metrics.get("community_score_total")
        if community_total is not None:
            try:
                summary_parts.append(
                    f"Community impact score: {float(community_total):.0f}/100."
                )
            except (ValueError, TypeError):
                pass

        policy_flag = metrics.get("policy_influence_flag")
        policy_desc = _safe_str(metrics.get("policy_description"))
        if policy_flag and policy_desc:
            summary_parts.append(f"A policy outcome was documented: {policy_desc}.")
        elif policy_flag:
            summary_parts.append("A policy or advocacy outcome was documented.")

    # Equity
    equity = intake.get("equity_flag")
    if equity is True or _is_title1(teacher_context):
        summary_parts.append(
            "This project serves an underserved or Title I community, "
            "reflecting TCI's commitment to climate equity."
        )

    # Sustained action
    sustained = intake.get("sustained_action")
    if sustained is True:
        summary_parts.append(
            "The project is designed to continue beyond the class period, "
            "creating lasting impact in the school or community."
        )

    return " ".join(summary_parts)


def _build_funder_summary_llm(seed: str, intake: dict, metrics: dict) -> str:
    """
    LLM upgrade path for funder_summary. Called only when LIVE_LLM=1.
    Passes the deterministic seed to the LLM for fluency improvement.
    Falls back to the seed on any failure.
    """
    try:
        from langchain_openai import AzureChatOpenAI

        llm = AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            temperature=0.3,
            max_tokens=300,
        )

        prompt = (
            "You are helping write a grant report paragraph for a climate education nonprofit. "
            "Rewrite the following paragraph to be more fluent and compelling for a foundation funder. "
            "Keep all facts exactly as stated. Do not add any information not present in the input. "
            "Do not include student names or personal data. Output one paragraph only, no preamble.\n\n"
            f"Draft: {seed}"
        )

        response = llm.invoke(prompt)
        result = response.content.strip()
        return result if result else seed

    except Exception:
        return seed


def build_funder_summary(
    intake: dict,
    metrics: dict,
    teacher_context: Optional[TeacherContext] = None,
) -> str:
    """
    Return a funder summary paragraph.
    Always deterministic by default; LLM enhancement gated behind LIVE_LLM=1.
    """
    seed = build_funder_summary_deterministic(intake, metrics, teacher_context)
    if os.getenv("LIVE_LLM", "0") == "1":
        return _build_funder_summary_llm(seed, intake, metrics)
    return seed


# ─────────────────────────────────────────
# D. MAP EXPORT GENERATION
# ─────────────────────────────────────────

def build_map_export(
    intake: dict,
    metrics: dict,
    teacher_context: Optional[TeacherContext] = None,
    jotform_submitted: bool = False,
) -> dict[str, Any]:
    """
    Build the Moore Foundation map export JSON.

    Gate: map_export_json is only generated when jotform_submitted=True.

    Rationale: The Moore Foundation map displays confirmed, complete projects.
    Publishing an incomplete or in-progress record would misrepresent TCI's
    impact and could not be retracted easily from the map backend. The Jotform
    submission is the teacher's confirmation that the project is complete and
    they consent to public display.

    Returns {} if jotform_submitted is False or falsy.
    Does not include personally identifying information (no names, emails,
    addresses). Location is at city/country level only.
    """
    if not jotform_submitted:
        return {}

    lab_name      = _safe_str(intake.get("canonical_lab_name"))
    project_type  = _safe_str(intake.get("project_type"))
    thematic      = _safe_str(intake.get("thematic_topic"))
    grade_band    = _safe_str(intake.get("grade_band"))
    track_val     = intake.get("track")
    track_str     = "A" if (track_val == Track.A or track_val == "A") else "B"

    student_count = _best_student_count(intake) or _safe_student_count(metrics.get("reach_estimate"))
    partner_count = metrics.get("partnership_count", 0)
    community_total = metrics.get("community_score_total")
    co2_lbs       = metrics.get("co2_reduction_lbs")
    sustained     = intake.get("sustained_action")
    equity        = intake.get("equity_flag")

    city         = ""
    country      = ""
    state_prov   = ""
    school_name  = ""
    if teacher_context:
        city        = _safe_str(getattr(teacher_context, "city", ""))
        country     = _safe_str(getattr(teacher_context, "country", ""))
        state_prov  = _safe_str(getattr(teacher_context, "state_province", ""))
        school_name = _safe_str(getattr(teacher_context, "school_name", ""))

    duration_weeks = None
    raw_dur = intake.get("project_duration_weeks")
    if raw_dur is not None:
        try:
            duration_weeks = int(raw_dur)
        except (ValueError, TypeError):
            pass

    export: dict[str, Any] = {
        "lab_name":                  lab_name,
        "project_type":              project_type,
        "thematic_topic":            thematic,
        "track":                     track_str,
        "grade_band":                grade_band,
        "num_students":              student_count,
        "community_partnerships_count": partner_count,
        "sustained_action":          sustained,
        "equity_flag":               equity,
        # Location — city/state/country level only (no street address)
        "school_name":               school_name,
        "city":                      city,
        "state_province":            state_prov,
        "country":                   country,
        # Impact metrics
        "community_score_total":     float(community_total) if community_total is not None else None,
        "co2_reduction_lbs":         float(co2_lbs) if co2_lbs is not None else None,
        # Project timeline
        "project_duration_weeks":    duration_weeks,
        "submission_date":           date.today().isoformat(),
        # Coordinates are placeholders — real geocoding is out of scope for POC.
        # TCI's map backend should resolve lat/lng from city+country.
        "lat":                       None,
        "lng":                       None,
    }

    return export


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def run_agent4(
    state: object,
    jotform_submitted: bool = False,
) -> object:
    """
    Primary callable for Agent 4. Reads state, writes to state.reporting.

    Parameters:
        state             Real ProjectState or any object with .structured_intake,
                          .impact_metrics, .raw_input, .teacher_context attributes.
        jotform_submitted When True, map_export_json is generated and written.
                          Defaults to False — incomplete projects are not published.

    Behaviour:
        - Fully recomputes all reporting outputs on each call (idempotent).
        - Does NOT accumulate or append across runs.
        - Safe to call at any project phase: planning, implementing, analyzing.
        - Uses state.update_reporting() if available (real ProjectState),
          otherwise sets state.reporting directly.

    Does NOT write to state.structured_intake or state.impact_metrics.
    Does NOT make LLM calls unless LIVE_LLM=1.
    Does NOT store personally identifying information.
    """
    raw_intake     = getattr(state, "structured_intake", None)
    raw_metrics    = getattr(state, "impact_metrics", None)
    raw_input      = getattr(state, "raw_input", None)
    teacher_ctx    = getattr(state, "teacher_context", None)

    intake  = _intake_dict(raw_intake)
    metrics = _metrics_dict(raw_metrics)

    # ── A. Logic model ────────────────────────────────────────────
    logic_model = build_logic_model(intake, metrics, teacher_ctx)
    logic_model_text = logic_model.to_text()

    # ── B. Jotform draft ─────────────────────────────────────────
    jotform_draft = build_jotform_draft(intake, metrics, raw_input, teacher_ctx)

    # ── C. Funder summary ─────────────────────────────────────────
    funder_summary = build_funder_summary(intake, metrics, teacher_ctx)

    # ── D. Map export (gated) ─────────────────────────────────────
    map_export = build_map_export(intake, metrics, teacher_ctx, jotform_submitted)

    # ── Write to state.reporting ──────────────────────────────────
    updates = dict(
        logic_model=logic_model,
        logic_model_text=logic_model_text,
        jotform_draft=jotform_draft,
        funder_summary=funder_summary,
        map_export_json=map_export,
    )

    if hasattr(state, "update_reporting"):
        state.update_reporting(**updates)
    else:
        # Test _FakeState or plain object
        if not hasattr(state, "reporting") or state.reporting is None:
            state.reporting = type("Reporting", (), {})()
        for k, v in updates.items():
            setattr(state.reporting, k, v)

    return state

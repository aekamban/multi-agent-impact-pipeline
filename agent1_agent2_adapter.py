"""
agent1_agent2_adapter.py
TCImpact — Handoff Adapter: Agent 1 → Agent 2
==============================================

Converts Agent 1 output (response_text, metadata) into a RawInput object
that Agent 2's process_submission() accepts.

Why this adapter exists
-----------------------
Agent 1 is a conversational / retrieval / guidance layer. It speaks to
teachers in natural language, retrieves lab content via RAG, and routes
curriculum standards. Its output is a (str, dict) tuple — not a structured
ProjectState field.

Agent 2 is the system of record for structured state. It owns the canonical
lab name, student count normalisation, track assignment, partner extraction,
and all downstream data quality. Nothing becomes "official" until Agent 2
has processed it.

The adapter is the seam between these two contracts. It is intentionally
thin: it does not interpret, score, or add information. It only maps what
Agent 1 already knows into RawInput fields, falling back to the original
teacher message when Agent 1 provides nothing structured.

Why Agent 1 does not write to the database
-------------------------------------------
Agent 1 does not know whether this is a new project or an update to an
existing one. It does not know the session_id, teacher_id, or project_id.
It is stateless across turns by design — it receives context as a dict
and returns text. Writing to the database requires knowing the full
longitudinal record, which is Agent 2's (and the adapter's caller's)
responsibility.

Why Agent 2 remains the system of record
-----------------------------------------
Agent 1 extracts target_lab from free text heuristically — it may be wrong
or ambiguous. Agent 2 applies fuzzy matching against the canonical alias
table and returns a confidence score. That confidence score drives warnings,
low-confidence flags, and downstream funder reporting quality. Bypassing
Agent 2 would silently lose those quality signals.

What this adapter assumes about Agent 1 output
-----------------------------------------------
- response_text: always a non-empty str (may be a clarification question)
- metadata["mode"]: one of "teacher" | "student" | "math"
- metadata["target_lab"]: Optional[str] — lab name extracted by standards_router
  (teacher mode only; may be None if Agent 1 couldn't identify it)
- metadata["retrieved_chunks"]: list of dicts with key "lab_name"
  (teacher + student modes; empty list for math mode)
- metadata["standards_result"]["matched_labs"]: list of lab name strings
  (teacher mode only; may be absent)
- metadata["clarification_returned"]: bool — True when Agent 1 asked a
  clarification question and has no structured output yet
- metadata["socratic"]["detected_signals"]: list of signal strings
  (student mode only; used to enrich raw_additional_notes)

What would need to change for multi-turn production use
-------------------------------------------------------
Currently the adapter processes one turn. In production:
- The caller should maintain a session accumulator that merges RawInput
  fields across turns (e.g. lab name confirmed in turn 1, student count
  provided in turn 3).
- The adapter should accept a prior_raw_input and merge rather than replace.
- Agent 2 should be called with the merged RawInput, not per-turn input.
This adapter is intentionally scoped to single-turn for demo stability.
"""

from __future__ import annotations

from typing import Any, Optional

from project_state import RawInput, TeacherContext


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

# Maximum character length for any raw text field written to RawInput.
# Agent 1 responses can be very long; we truncate to keep intake focused.
_MAX_DESCRIPTION_LEN = 2000
_MAX_NOTES_LEN       = 1000
_MAX_PARTNERS_LEN    = 500


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def _safe(value: Any, max_len: int = _MAX_DESCRIPTION_LEN) -> str:
    """Coerce to str, strip whitespace, truncate. Returns '' for None."""
    if value is None:
        return ""
    try:
        s = str(value).strip()
    except Exception:
        return ""
    return s[:max_len]


def _first_lab_from_chunks(retrieved_chunks: list) -> str:
    """
    Extract the first lab_name from Agent 1's retrieved_chunks list.
    Each chunk is a dict with at minimum a 'lab_name' key.
    Returns '' if list is empty or malformed.
    """
    for chunk in retrieved_chunks:
        if isinstance(chunk, dict):
            name = _safe(chunk.get("lab_name", ""))
            if name:
                return name
    return ""


def _first_lab_from_matched(matched_labs: list) -> str:
    """
    Extract the first entry from standards_result['matched_labs'].
    Returns '' if list is empty or malformed.
    """
    if matched_labs and isinstance(matched_labs, list):
        return _safe(matched_labs[0])
    return ""


def _resolve_lab_name(metadata: dict, original_message: str) -> str:
    """
    Determine the best available lab name from Agent 1 metadata.

    Priority:
      1. metadata["target_lab"]  — extracted by standards_router from free text
         (most specific; may be None if Agent 1 couldn't identify it)
      2. metadata["standards_result"]["matched_labs"][0]  — broader match
      3. metadata["retrieved_chunks"][0]["lab_name"]  — first retrieved lab
      4. ""  — leave blank; Agent 2 will attempt fuzzy matching on description

    We do NOT scrape lab names from the response_text prose — that is too
    fragile. Agent 2's fuzzy matching is better at that job.
    """
    # Priority 1: target_lab
    target = _safe(metadata.get("target_lab", ""))
    if target:
        return target

    # Priority 2: matched_labs from standards_result
    standards = metadata.get("standards_result") or {}
    matched = standards.get("matched_labs") or []
    first_matched = _first_lab_from_matched(matched)
    if first_matched:
        return first_matched

    # Priority 3: first retrieved chunk
    chunks = metadata.get("retrieved_chunks") or []
    first_chunk = _first_lab_from_chunks(chunks)
    if first_chunk:
        return first_chunk

    return ""


def _resolve_project_description(
    response_text: str,
    original_message: str,
    metadata: dict,
) -> str:
    """
    Determine the best project description for raw_project_description.

    Design rule: prefer the original teacher message over the Agent 1
    response. The teacher's own words describe their project; Agent 1's
    response is guidance/questions, not a project description.

    Exception: if Agent 1 returned a clarification question
    (clarification_returned=True), the teacher hasn't described their
    project yet — use the original message as the best available signal.

    We never use Agent 1's response_text as the project description
    directly, because it contains Socratic questions, standards tables,
    and curriculum guidance — not project facts.
    """
    msg = _safe(original_message)
    if msg:
        return msg
    # Last resort: first 200 chars of response as minimal signal
    return _safe(response_text, 200)


def _resolve_additional_notes(
    response_text: str,
    metadata: dict,
    original_message: str,
) -> str:
    """
    Build raw_additional_notes from available signals.

    For student mode: include detected_signals from the Socratic engine —
    these describe what the student is thinking about (e.g. "feasibility",
    "community", "scale") and are useful context for Agent 2's rubric scoring.

    For teacher mode: include the curriculum standard and subject area from
    context if available — these enrich grade_band and standards alignment
    downstream.

    For math mode: note the calculation step if available.

    Never includes personal data.
    """
    parts: list[str] = []
    mode = metadata.get("mode", "")

    if mode == "student":
        socratic = metadata.get("socratic") or {}
        signals = socratic.get("detected_signals") or []
        if signals:
            parts.append(f"Student signals detected: {', '.join(str(s) for s in signals)}")
        category = _safe(socratic.get("category", ""))
        if category:
            parts.append(f"Socratic category: {category}")

    elif mode == "teacher":
        standards = metadata.get("standards_result") or {}
        system = _safe(standards.get("system", ""))
        if system and system != "unknown":
            parts.append(f"Curriculum system: {system}")
        stage = _safe(standards.get("stage", ""))
        if stage and stage != "unknown":
            parts.append(f"Standards stage: {stage}")

    elif mode == "math":
        # Math mode has no pre-retrieval; note this is an En-ROADS calculation session
        parts.append("Mode: En-ROADS carbon calculation support session")

    return _safe("; ".join(parts), _MAX_NOTES_LEN)


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────

def adapt_agent1_to_raw_input(
    original_message: str,
    agent1_response_text: str,
    agent1_metadata: dict,
    teacher_context: Optional[TeacherContext] = None,
) -> RawInput:
    """
    Convert Agent 1 output into a RawInput for Agent 2.

    Parameters
    ----------
    original_message : str
        The teacher's original message to Agent 1 (unmodified).
        This is used as raw_project_description when Agent 1 provides
        no more specific structured description.

    agent1_response_text : str
        Agent 1's conversational response (guidance, Socratic questions,
        standards table etc.). NOT used as project description — see docstring
        on _resolve_project_description().

    agent1_metadata : dict
        The metadata dict returned by run_agent1(). Expected keys:
        mode, target_lab, retrieved_chunks, standards_result,
        clarification_returned, socratic.
        All keys are optional — adapter is defensive about missing values.

    teacher_context : Optional[TeacherContext]
        If provided, used to enrich location and school fields.
        Never overrides structured fields from Agent 1 metadata.

    Returns
    -------
    RawInput
        Populated with whatever Agent 1 could provide. Missing fields
        are left as "" — Agent 2 handles partial submissions gracefully.

    Notes
    -----
    When clarification_returned=True, Agent 1 asked a clarification
    question and has not yet gathered project information. The returned
    RawInput will have raw_project_description=original_message and
    everything else blank. Agent 2 will flag low confidence, which is
    the correct behaviour — it signals to the UI that more information
    is needed before the project can be structured.

    This adapter never invents data. If a field is unavailable, it is "".
    """
    metadata = agent1_metadata or {}

    # ── Lab name ──────────────────────────────────────────────────────────────
    raw_lab_name = _resolve_lab_name(metadata, original_message)

    # ── Project description ───────────────────────────────────────────────────
    raw_project_description = _resolve_project_description(
        agent1_response_text, original_message, metadata
    )

    # ── Additional notes ──────────────────────────────────────────────────────
    raw_additional_notes = _resolve_additional_notes(
        agent1_response_text, metadata, original_message
    )

    # ── Location ──────────────────────────────────────────────────────────────
    # Prefer teacher_context fields over anything Agent 1 might have.
    # Agent 1 does not extract location from free text.
    raw_location = ""
    if teacher_context:
        city  = _safe(getattr(teacher_context, "city", ""))
        state = _safe(getattr(teacher_context, "state_province", ""))
        country = _safe(getattr(teacher_context, "country", ""))
        parts = [p for p in [city, state, country] if p]
        raw_location = ", ".join(parts)

    # ── Fields Agent 1 never provides ────────────────────────────────────────
    # Student count: Agent 1 does not ask for this — left blank.
    # Community partners: Agent 1 does not extract these — left blank.
    # The teacher will provide these through subsequent turns or the Jotform.

    return RawInput(
        raw_lab_name=raw_lab_name,
        raw_project_description=raw_project_description,
        raw_student_count_text="",      # Agent 1 never provides this
        raw_additional_notes=raw_additional_notes,
        raw_community_partners="",      # Agent 1 never provides this
        raw_location=raw_location,
        submission_source="in_app",
    )


def build_raw_input_from_message(
    original_message: str,
    teacher_context: Optional[TeacherContext] = None,
) -> RawInput:
    """
    Minimal fallback: build RawInput directly from the teacher's message
    when Agent 1 has not run yet (e.g. offline, skipped, or unavailable).

    This path is used by the thin pipeline wrapper when LIVE_LLM=0 and
    Agent 1 cannot be invoked. It ensures the rest of the pipeline
    (Agents 2, 3, 4) can always run with at least some input.
    """
    raw_location = ""
    if teacher_context:
        city    = _safe(getattr(teacher_context, "city", ""))
        state   = _safe(getattr(teacher_context, "state_province", ""))
        country = _safe(getattr(teacher_context, "country", ""))
        parts   = [p for p in [city, state, country] if p]
        raw_location = ", ".join(parts)

    return RawInput(
        raw_lab_name="",
        raw_project_description=_safe(original_message),
        raw_student_count_text="",
        raw_additional_notes="",
        raw_community_partners="",
        raw_location=raw_location,
        submission_source="in_app",
    )

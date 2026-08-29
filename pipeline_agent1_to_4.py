"""
pipeline_agent1_to_4.py
Thin Pipeline Wrapper: Agent 1 → 2 → 3 → 4
=======================================================

A single callable that runs one teacher message through the full pipeline:

    run_agent1_to_4_pipeline(message, mode, context, teacher_context, ...)
        → (agent1_response, agent1_metadata, raw_input, final_state)

Design constraints:
    - This is a demo integration helper, not a production orchestrator.
    - It does not manage sessions, DB writes, or multi-turn state.
    - Agent 1 is gated behind LIVE_LLM=1 — without it, the pipeline
      runs Agents 2→3→4 using only the original teacher message.
    - All agents are called in sequence; no parallelism.
    - The caller is responsible for DB persistence via project_state_adapter.

For iterative multi-turn use (post-demo):
    - Maintain a session accumulator that merges RawInput fields across turns.
    - Pass prior_raw_input to adapt_agent1_to_raw_input() for merging.
    - Only call Agent 2 when enough fields have accumulated.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from agent1_agent2_adapter import adapt_agent1_to_raw_input, build_raw_input_from_message
from agent2 import process_submission

from project_state import RawInput, TeacherContext


def run_agent1_to_4_pipeline(
    teacher_message: str,
    mode: str = "teacher",
    agent1_context: Optional[dict] = None,
    teacher_context: Optional[TeacherContext] = None,
    chat_history: Optional[list] = None,
    used_question_ids: Optional[list] = None,
    turn_count: int = 0,
    jotform_submitted: bool = False,
) -> tuple[str, dict, RawInput, Any]:
    """
    Run a teacher message through the full Agent 1 → 2 → 3 → 4 pipeline.

    Parameters
    ----------
    teacher_message : str
        The teacher's raw input (e.g. "We want to do a composting project
        with our agriculture lab. About 25 students, grades 9-10.").
    mode : str
        Agent 1 mode: "teacher" | "student" | "math". Default "teacher".
    agent1_context : dict, optional
        Context dict for Agent 1 (subject_area, grade_band, etc.).
        See agent1.py for expected keys. Defaults to empty dict.
    teacher_context : TeacherContext, optional
        Teacher school/location context for Agents 2, 3, 4.
    chat_history : list, optional
        Prior conversation turns for Agent 1 (multi-turn; not used in demo).
    used_question_ids : list, optional
        Socratic question IDs already used (student mode).
    turn_count : int
        Turn number in the conversation (0 = first turn).
    jotform_submitted : bool
        Passed to Agent 4 to gate map_export_json generation.

    Returns
    -------
    tuple of:
        agent1_response : str
            Agent 1's conversational response, or "" if skipped.
        agent1_metadata : dict
            Agent 1's metadata dict, or {} if skipped.
        raw_input : RawInput
            The RawInput built by the adapter for Agent 2.
        final_state : ProjectState
            The fully populated ProjectState after Agents 2, 3, 4.

    Notes
    -----
    Agent 1 only runs when LIVE_LLM=1. Without it:
        - agent1_response = ""
        - agent1_metadata = {"mode": mode, "skipped": True}
        - raw_input is built directly from teacher_message via
          build_raw_input_from_message()

    This means Agents 2→3→4 always run regardless of LLM availability,
    ensuring the pipeline is testable offline.
    """
    agent1_context = agent1_context or {}
    use_llm = os.getenv("LIVE_LLM", "0") == "1"

    # ── Step 1: Agent 1 (LLM-gated) ──────────────────────────────────────────
    if use_llm:
        from agent1 import run_agent1
        agent1_response, agent1_metadata = run_agent1(
            mode=mode,
            user_input=teacher_message,
            context=agent1_context,
            chat_history=chat_history or [],
            used_question_ids=used_question_ids or [],
            turn_count=turn_count,
        )
        # ── Step 2: Adapt Agent 1 output → RawInput ──────────────────────────
        raw_input = adapt_agent1_to_raw_input(
            original_message=teacher_message,
            agent1_response_text=agent1_response,
            agent1_metadata=agent1_metadata,
            teacher_context=teacher_context,
        )
    else:
        # Offline fallback: skip Agent 1, build minimal RawInput from message
        agent1_response = ""
        agent1_metadata = {"mode": mode, "skipped": True}
        raw_input = build_raw_input_from_message(
            original_message=teacher_message,
            teacher_context=teacher_context,
        )

    # ── Step 3: Agent 2 — Intake & Structuring ───────────────────────────────
    state = process_submission(raw_input, teacher_context=teacher_context)

    # ── Step 4: Agent 3 — Impact Calculator ──────────────────────────────────
    from agent3 import run_agent3
    state = run_agent3(state)

    # ── Step 5: Agent 4 — Funder Summary & Reporting ─────────────────────────
    from agent4 import run_agent4
    state = run_agent4(state, jotform_submitted=jotform_submitted)

    return agent1_response, agent1_metadata, raw_input, state

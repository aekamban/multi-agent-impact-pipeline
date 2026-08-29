"""
socratic_engine.py — Agent 1 Socratic Question Selector (v3)

Changes from v2:
- ALL random calls replaced with deterministic index-based selection.
  Category fallback uses highest-weight category, not weighted random.
  Question selection uses first trigger-matched question, not random.
  Growth reflection cycles by (turn_count % len) — same input → same output.
  Strength mirror cycles by turn_count — predictable for demo/QA.
- This makes the engine fully reproducible: given identical inputs the
  output is always identical. No seeding required.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent


def _find_file(name: str) -> Optional[Path]:
    for root in [_HERE, _HERE / "documents"]:
        p = root / name
        if p.exists():
            return p
    return None


def _load_bank() -> dict:
    p = _find_file("socratic_question_bank.json")
    if not p:
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


_BANK = _load_bank()

_CATEGORIES: dict[str, list[dict]] = {
    cat["category"]: cat["questions"]
    for cat in _BANK.get("question_bank", [])
}
_SIGNAL_KEYWORDS: dict[str, list[str]] = _BANK.get("signal_detection", {})
_PHASE_WEIGHTS: dict[str, dict[str, float]] = (
    _BANK.get("question_engine_logic", {}).get("phase_weighting", {})
)
_GROWTH_QUESTIONS: list[str] = (
    _BANK.get("growth_reflection_questions", {}).get("questions", [])
    or ["What small next step feels possible right now?"]
)
_STRENGTH_PHRASES: list[str] = (
    _BANK.get("strength_language_pool", {}).get("phrases", [])
    or ["It sounds like you are thinking deeply about this."]
)
_CONTEXT_FLAGS: list[str] = (
    _BANK.get("context_sensitivity_flags", {}).get("context_sensitive_triggers", [])
)

# Signal → category: direct mapping takes priority over phase weighting
_SIGNAL_CATEGORY_MAP: dict[str, str] = {
    "project_too_small":       "AMBITION_BOOSTERS",
    "limited_scope":           "AMBITION_BOOSTERS",
    "blocker":                 "PIVOT_SUPPORTERS",
    "unexpected_blocker":      "PIVOT_SUPPORTERS",
    "math_anxiety":            "MATH_CONFIDENCE_BUILDERS",
    "discouragement":          "SELF_CONFIDENCE_BUILDERS",
    "low_confidence":          "SELF_CONFIDENCE_BUILDERS",
    "low_motivation":          "SELF_CONFIDENCE_BUILDERS",
    "missing_evidence":        "RIGOR_BUILDERS",
    "systems_thinking_needed": "RIGOR_BUILDERS",
    "low_academic_depth":      "RIGOR_BUILDERS",
}


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class SocraticPromptBlock:
    """Structured output from the Socratic engine, injected into student mode prompt."""

    detected_signals: list[str]
    primary_category: str
    phase: str
    primary_question: str
    question_id: str
    follow_up_prompt: str
    growth_reflection: str
    depth_level: int
    lenses_to_invoke: list[str]
    strength_mirror: Optional[str]
    is_distressed: bool
    needs_confidence_check: bool
    context_sensitive_flag: bool

    def format_for_prompt(self) -> str:
        lines = [
            "SOCRATIC ENGINE OUTPUT",
            f"  Detected signals  : {self.detected_signals or ['none']}",
            f"  Active category   : {self.primary_category}",
            f"  Phase             : {self.phase}",
            f"  Depth level       : {self.depth_level}",
            f"  Lenses to invoke  : {self.lenses_to_invoke or ['not specified']}",
            "",
            "REQUIRED RESPONSE STRUCTURE:",
            "  1. (Optional) One brief warm acknowledgment of what the student said.",
        ]
        if self.is_distressed:
            lines.append(
                "     ⚠ Student appears distressed — validate their feelings "
                "BEFORE asking any challenge question."
            )
        if self.strength_mirror:
            lines.append(
                f"  2. Strength mirror (use at most ONCE per conversation): "
                f'"{self.strength_mirror}"'
            )
        else:
            lines.append("  2. (No strength mirror this turn.)")

        lines += [
            "  3. Ask this PRIMARY QUESTION exactly as written "
            "(do not skip, do not convert to a statement):",
            f'     "{self.primary_question}"',
        ]
        if self.follow_up_prompt:
            lines.append(
                f"  4. If student response is very brief, follow with: "
                f'"{self.follow_up_prompt}"'
            )
        lines += [
            "  5. RESERVE QUESTION (use instead of the primary question if the student",
            "     has already engaged substantively and reflection fits the moment):",
            f'     "{self.growth_reflection}"',
            "     Do NOT ask both the primary question and this one in the same turn.",
            "",
            "ABSOLUTE RULES:",
            "  - Ask ONE question per turn. Either the primary question (step 3) OR the",
            "    reserve reflection (step 5) — never both. Default to step 3.",
            "  - Never give a direct answer or solution before the student engages.",
            "  - No bullet points or numbered lists in your response.",
            "  - Keep response under 150 words.",
            "  - Only suggest a direction if student is still stuck after 2 full turns.",
        ]
        if self.lenses_to_invoke:
            lines.append(
                f"  - Gently open the "
                f"{'/'.join(self.lenses_to_invoke)} lens if not yet mentioned."
            )
        return "\n".join(lines)


# ── Signal detection ───────────────────────────────────────────────────────────

def detect_signals(message: str, context: dict | None = None) -> list[str]:
    """Keyword-match student message against signal_detection list. Fully deterministic."""
    message_lower = message.lower()
    active: list[str] = []
    for signal_name, keywords in _SIGNAL_KEYWORDS.items():
        if signal_name == "description":
            continue
        if any(kw.lower() in message_lower for kw in keywords):
            active.append(signal_name)
    if context:
        ctx_text = " ".join(str(v) for v in context.values()).lower()
        if any(t.lower() in ctx_text for t in _CONTEXT_FLAGS):
            active.append("context_sensitive")
    return active


def _is_distressed(signals: list[str]) -> bool:
    return any(s in signals for s in ("discouragement", "low_confidence", "low_motivation"))


# ── Deterministic category selection ──────────────────────────────────────────

def _select_category(signals: list[str], phase: str) -> str:
    """
    Deterministic: signal mapping first; phase-weight fallback picks the
    highest-weight category (no random). Distressed students never get
    AMBITION_BOOSTERS.
    """
    distressed = _is_distressed(signals)
    for signal in signals:
        cat = _SIGNAL_CATEGORY_MAP.get(signal)
        if cat:
            if cat == "AMBITION_BOOSTERS" and distressed:
                return "SELF_CONFIDENCE_BUILDERS"
            return cat

    # Phase-weight fallback: pick highest-weight category (deterministic)
    weights = _PHASE_WEIGHTS.get(phase, _PHASE_WEIGHTS.get("planning", {}))
    if not weights:
        return "AMBITION_BOOSTERS"
    best = max(weights, key=lambda c: weights[c])
    if best == "AMBITION_BOOSTERS" and distressed:
        # Pick second-highest
        ranked = sorted(weights, key=lambda c: weights[c], reverse=True)
        for cat in ranked:
            if cat != "AMBITION_BOOSTERS":
                return cat
    return best


# ── Deterministic question selection ──────────────────────────────────────────

def _select_question(
    category: str,
    signals: list[str],
    phase: str,
    depth_level: int,
    used_ids: list[str],
    turn_count: int,
) -> Optional[dict]:
    """
    Deterministic selection:
    1. Filter by phase, then depth.
    2. Remove cooldown IDs.
    3. Among remaining, prefer questions whose trigger matches a detected signal.
       Within that set pick by (turn_count % len) — stable across identical inputs.
    4. If no trigger match, pick by (turn_count % len) of available pool.
    5. If all exhausted by cooldown, reset cooldown and retry.
    """
    questions = _CATEGORIES.get(category, [])
    if not questions:
        return None

    # Phase filter
    phase_ok = [q for q in questions if q.get("phase") in (phase, "any")]
    if not phase_ok:
        phase_ok = questions

    # Depth filter — prefer exact, then ≤, then all
    depth_exact = [q for q in phase_ok if q.get("depth_level") == depth_level]
    depth_leq   = [q for q in phase_ok if q.get("depth_level", 1) <= depth_level]
    depth_pool  = depth_exact or depth_leq or phase_ok

    def _pick_from(pool: list[dict]) -> dict:
        return pool[turn_count % len(pool)]

    # Cooldown removal
    available = [q for q in depth_pool if q.get("id") not in used_ids]
    if not available:
        available = depth_pool  # cooldown reset

    # Prefer trigger-matched questions
    for signal in signals:
        trigger_matched = [q for q in available if q.get("trigger") == signal]
        if trigger_matched:
            return _pick_from(trigger_matched)

    return _pick_from(available)


# ── Public API ─────────────────────────────────────────────────────────────────

def select_questions(
    message: str,
    phase: str,
    context: dict | None = None,
    depth_level: int = 1,
    used_question_ids: list[str] | None = None,
    turn_count: int = 0,
) -> SocraticPromptBlock:
    """
    Deterministic question selection. Identical inputs always produce identical output.

    Args:
        message: student's latest message
        phase: "planning" | "implementing" | "analyzing"
        context: session context dict
        depth_level: 1-3, escalates with engagement
        used_question_ids: IDs used in recent turns (cooldown, student-mode scoped)
        turn_count: turns elapsed (drives deterministic cycling within pools)
    """
    context = context or {}
    used_question_ids = used_question_ids or []

    signals      = detect_signals(message, context)
    distressed   = _is_distressed(signals)
    ctx_sensitive = "context_sensitive" in signals

    category = _select_category(signals, phase)
    q_obj    = _select_question(
        category, signals, phase, depth_level, used_question_ids, turn_count
    )

    if q_obj:
        primary_q = q_obj["question"]
        q_id      = q_obj["id"]
        follow_up = q_obj.get("follow_up_prompt", "")
        lenses    = q_obj.get("lenses", [])
    else:
        primary_q = "What feels most important to you about this project right now?"
        q_id      = "FALLBACK"
        follow_up = "Can you say more about that?"
        lenses    = []

    # Growth reflection: cycle deterministically by turn_count
    growth_q = _GROWTH_QUESTIONS[turn_count % len(_GROWTH_QUESTIONS)]

    # Strength mirror: use at turns 2, 3, 4 when not distressed.
    # Deterministic: turn_count mod len(_STRENGTH_PHRASES) picks which phrase.
    # "STRENGTH_USED" sentinel in used_question_ids prevents reuse.
    use_strength = (
        not distressed
        and turn_count in (2, 3, 4)
        and "STRENGTH_USED" not in used_question_ids
    )
    strength = _STRENGTH_PHRASES[turn_count % len(_STRENGTH_PHRASES)] if use_strength else None

    return SocraticPromptBlock(
        detected_signals=signals,
        primary_category=category,
        phase=phase,
        primary_question=primary_q,
        question_id=q_id,
        follow_up_prompt=follow_up,
        growth_reflection=growth_q,
        depth_level=depth_level,
        lenses_to_invoke=lenses if isinstance(lenses, list) else [lenses],
        strength_mirror=strength,
        is_distressed=distressed,
        needs_confidence_check="math_anxiety" in signals,
        context_sensitive_flag=ctx_sensitive,
    )


# ── Quick test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        ("Small project + planning",
         "We just want to make a poster. Is that okay?", "planning"),
        ("Discouragement + implementing",
         "This is pointless. Climate change is too big. What's the point?", "implementing"),
        ("Math anxiety",
         "I hate math and I don't understand the CO2 calculation.", "implementing"),
        ("Blocker",
         "The principal said no and we can't do it anymore.", "implementing"),
        ("Missing evidence",
         "I think our project will probably help reduce carbon.", "analyzing"),
    ]
    print("\n=== Determinism check: same input twice ===")
    msg, phase = "We just want to make a poster.", "planning"
    b1 = select_questions(msg, phase, turn_count=0)
    b2 = select_questions(msg, phase, turn_count=0)
    assert b1.primary_question == b2.primary_question, "NOT DETERMINISTIC!"
    assert b1.growth_reflection == b2.growth_reflection, "Growth NOT DETERMINISTIC!"
    print(f"  ✓ Same question both calls: '{b1.primary_question[:60]}...'")

    for label, message, phase in cases:
        print(f"\n{'='*55}\n{label}")
        block = select_questions(message, phase)
        print(f"  signals={block.detected_signals}")
        print(f"  category={block.primary_category}, q_id={block.question_id}")
        print(f"  Q: {block.primary_question}")
        print(f"  Growth: {block.growth_reflection}")

"""
agent1.py — Agent 1: Learning Lab Expert + Curriculum Integration Assistant (v3)
Uses LangGraph create_react_agent (LangChain 1.x / LangGraph 0.2+).

Changes from v2:
- Retrieval enforced in code: retrieve_with_metadata() is called before the
  LLM agent is invoked for teacher and student modes. Retrieved chunks are
  injected directly into the system prompt. The ReAct tool remains available
  for the model to do additional targeted lookups, but the first retrieval
  cannot be skipped — it happens in Python before any LLM call.
- Clarification short-circuit: if standards_router returns needs_clarification=True,
  run_agent1() returns the fallback question immediately without touching the LLM.
- target_lab extracted from free text by standards_router and passed through
  to format_for_prompt(), so "How does Renewable Energy fit NGSS?" always
  surfaces that lab first in the standards block.
- Source metadata: run_agent1() returns retrieved_chunks list in metadata
  so every call is inspectable for grounding QA.
- used_question_ids is now passed in per call (student-mode scoped in UI),
  not stored app-globally.
"""

import os
import json
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

load_dotenv()

_HERE = Path(__file__).parent


def _find_file(name: str) -> Path | None:
    for root in [_HERE, _HERE / "documents"]:
        p = root / name
        if p.exists():
            return p
    return None


def _load_text(name: str) -> str:
    p = _find_file(name)
    return p.read_text(encoding="utf-8") if p else ""


PROMPT_STANDARDS_MD = _load_text("AGENT1_PROMPT_STANDARDS.md")

AgentMode = Literal["teacher", "student", "math"]


# ── LLM ────────────────────────────────────────────────────────────────────────

def _make_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_CHAT_DEPLOYMENT", "gpt-4-1"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        temperature=0.3,
        max_tokens=1200,
    )


# ── Supplemental RAG tool (for targeted follow-up lookups) ─────────────────────
# Primary retrieval is done in Python before any LLM call.
# This tool lets the model do additional targeted searches — but it is NOT
# the primary retrieval mechanism. The system prompt always contains pre-retrieved
# chunks from Python-side retrieval.

def _make_supplemental_rag_tool():
    from rag_ingestion import get_retriever
    retriever = get_retriever(k=3)

    @tool
    def search_lab_content(query: str) -> str:
        """
        Search the program's 11 learning lab documents for additional context on a specific
        topic, activity, or concept. Use this for targeted follow-up lookups after
        your initial context has been provided. Input: plain-English topic or question.
        """
        docs = retriever.invoke(query)
        if not docs:
            return "No additional lab content found for that query."
        parts = [
            f"[{doc.metadata.get('lab_name', '?')} | Track {doc.metadata.get('track', '?')}]\n"
            f"{doc.page_content.strip()}"
            for doc in docs
        ]
        return "\n\n---\n\n".join(parts)

    return search_lab_content


# ── System prompts ─────────────────────────────────────────────────────────────

def _teacher_system_prompt(
    context: dict,
    standards_block: str,
    retrieved_context: str,
) -> str:
    subject = context.get("subject_area", "your subject")
    grade   = context.get("grade_band", "your grade level")
    country = context.get("country", "US")
    unit    = context.get("current_unit", "your current unit")
    school  = context.get("school_type", "")
    local   = context.get("local_context", "")
    std     = context.get("curriculum_standard", "NGSS")

    return f"""You are the program's Curriculum Integration Assistant. Help teachers connect the program's climate Learning Labs to their mandatory curriculum without requiring them to rewrite it.

## TEACHER CONTEXT
Subject: {subject} | Grade: {grade} | Standard: {std} | Country: {country}
Current unit: {unit} | School type: {school} | Local context: {local}

## PRE-RETRIEVED LAB CONTENT (already retrieved — use this, do not skip)
The following content was retrieved from the program's learning lab documents before this conversation turn.
Ground your response in this content. Use search_lab_content only for targeted follow-up.

{retrieved_context}

## STRUCTURED STANDARDS DATA (from verified CSV files — not memory)
{standards_block}

## PROMPT STANDARDS REFERENCE
{PROMPT_STANDARDS_MD[:2500] if PROMPT_STANDARDS_MD else "(not loaded)"}

## RESPONSE STRUCTURE — follow exactly

**1. CONNECTION STATEMENT**
1-2 sentences the teacher can say to their department head. Plain language, no jargon.

**2. SPECIFIC STANDARD LINKS**
For US: cite 2-3 exact codes from the standards data above with plain-English explanation.
For IB/UK/Cambridge: give conceptual connections; note "full {std} alignment coming soon."
Always say "here are the strongest connections" — never claim exhaustiveness.
Never invent codes not present in the standards data.

**3. INTEGRATION SUGGESTION**
Name the specific concept + the specific unit they already teach.
Show where the lab fits as real-world context — not an add-on.

**4. PROJECT TYPE RECOMMENDATION**
2-3 concrete types. Include one that works with minimal resources.

**5. SOURCE TRANSPARENCY**
End with exactly this line:
"📚 Lab content from: [list lab names from PRE-RETRIEVED content] | Standards table: {std}"

## SPECIAL CASES
- "I can't do this in my subject": never accept. Ask "What are you teaching right now?" then find the connection.
- Tribal schools: lead with community connection and land stewardship BEFORE standards.
- State standards: note NGSS adoption varies by state when relevant.

## TONE
Warm, collegial, practical. Never give school administration advice.
"""


def _student_system_prompt(
    context: dict,
    socratic_block: str,
    retrieved_context: str,
) -> str:
    phase    = context.get("phase", "planning")
    grade    = context.get("grade_band", "high school")
    lab_name = context.get("lab_name", "your learning lab")
    project  = context.get("project_description", "")
    school   = context.get("school_type", "")

    return f"""You are the program's Student Climate Coach. You guide students through climate action projects using Socratic questions. Never give direct answers when a question will help them discover the answer.

## STUDENT CONTEXT
Phase: {phase} | Grade: {grade} | Lab: {lab_name}
Project: {project} | School type: {school}

## PRE-RETRIEVED LAB CONTENT (already retrieved — ground your coaching here)
{retrieved_context}

## THREE LENSES FRAMEWORK
Ecological: environmental systems and impacts
Economic: costs, incentives, resource realities
Sociocultural: who is affected, communities, values, histories

## HARD GUARDRAILS
- Never collect personally identifying information
- Never give medical, legal, or school administration advice
- Never be discouraging — find what is good in every idea first
- Never give a direct solution before asking at least two reflective questions
- All content must be appropriate for {grade} students
- If student mentions personal distress: express care, encourage a trusted adult

## SOCRATIC ENGINE OUTPUT — follow this structure exactly
{socratic_block}

## SOURCE TRANSPARENCY
End your response with (on its own line):
"🌱 Lab content from: {lab_name}"
"""


def _math_system_prompt(context: dict) -> str:
    confidence = int(context.get("math_confidence", 3))
    grade      = context.get("grade_band", "high school")
    project    = context.get("project_description", "")
    step       = context.get("current_calculation_step", "")
    scaffold   = (
        "gentle — start from the very beginning, ask what student already knows"
        if confidence <= 2 else
        "medium — show formula, have student plug in numbers"
        if confidence == 3 else
        "deep — move through arithmetic quickly, focus on interpretation"
    )

    return f"""You are the program's En-ROADS Math Coach. Help students work through carbon calculations step by step. Specialise in supporting students with math anxiety.

## STUDENT CONTEXT
Math confidence: {confidence}/5 → scaffold mode: {scaffold}
Grade: {grade} | Project: {project} | Current step: {step}

## EPA EMISSIONS FACTORS — USE EXACTLY THESE VALUES, NEVER ESTIMATE
| Source          | Per unit        | lbs CO2e | kg CO2e |
|-----------------|-----------------|----------|---------|
| Electricity US  | per kWh         | 0.851    | 0.386   |
| Natural gas     | per therm       | 11.7     | 5.3     |
| Gasoline        | per gallon      | 19.6     | 8.89    |
| Diesel          | per gallon      | 22.4     | 10.16   |
| Propane         | per gallon      | 12.7     | 5.74    |
| Beef            | per lb consumed | 12.25    | 5.55    |
| Landfill waste  | per ton         | 1,150    | 522     |

PROGRAM PROJECT BENCHMARK: 10,000 lbs CO2e reduction per project.
Always show: "Your result = X lbs — that is Y% of the 10,000 lb program benchmark."

## CALCULATION RULES — NEVER SKIP ANY STEP
1. State the formula: (quantity) × (emissions factor) = CO2e
2. Substitute the actual numbers, showing each one
3. Show the arithmetic step
4. State result with BOTH lbs AND kg
5. Sanity check: "Does this feel bigger or smaller than you expected?"
6. Benchmark connection: what % of the 10,000 lb target
7. State clearly what the next step is

## SCAFFOLDING BY CONFIDENCE
1-2: Ask what student already knows before showing formula. Celebrate each step.
     Analogy: "Think of CO2 like water in a bathtub — we're counting gallons."
3: Show formula, student plugs in numbers. Offer alternate explanation if stuck.
4-5: Move quickly through arithmetic. Focus on interpretation and policy implications.

## NEVER DO
- Give just the answer without the path
- Tell a student they are wrong without asking them to check their own work first
- Use minimising language ("that's just simple multiplication")
- Skip units — units help students catch their own errors

## SOURCE TRANSPARENCY
End every response with:
"📐 Emissions factors: EPA eGRID 2023 | Benchmark: 10,000 lb CO2e program target"
"""


# ── Output extraction ──────────────────────────────────────────────────────────

def _extract_output(result: dict) -> str:
    """Extract final text from LangGraph agent result messages."""
    for msg in reversed(result.get("messages", [])):
        if not hasattr(msg, "content") or not msg.content:
            continue
        if getattr(msg, "type", None) == "tool":
            continue
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list):
            return " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in msg.content
            )
    return ""


# ── Public API ─────────────────────────────────────────────────────────────────

def run_agent1(
    mode: AgentMode,
    user_input: str,
    context: dict,
    chat_history: list | None = None,
    used_question_ids: list[str] | None = None,  # student-mode scoped; caller manages
    turn_count: int = 0,
) -> tuple[str, dict]:
    """
    Run one turn of Agent 1. Returns (response_text, metadata_dict).

    Retrieval guarantee:
      Teacher and student modes call retrieve_with_metadata() in Python BEFORE
      the LLM agent runs. Retrieved chunks are injected into the system prompt.
      This cannot be skipped — it is not delegated to the model.

    Clarification short-circuit:
      If standards_router signals needs_clarification=True, returns the fallback
      question immediately without any LLM call.

    metadata_dict keys:
      - mode: the mode used
      - retrieved_chunks: list of {lab_name, track, preview} for every chunk
        retrieved in the pre-retrieval step (inspectable for QA)
      - retrieval_query: the query used for pre-retrieval
      - standards_result: teacher mode routing summary (teacher only)
      - target_lab: lab name extracted from teacher's message (teacher only)
      - socratic: Socratic engine output summary (student only)
      - clarification_returned: True when short-circuited (teacher only)
    """
    if mode not in ("teacher", "student", "math"):
        raise ValueError(
            f"Unknown mode: {mode!r}. Must be 'teacher', 'student', or 'math'."
        )

    chat_history = chat_history or []
    used_question_ids = used_question_ids or []
    metadata: dict = {"mode": mode}

    # ── TEACHER MODE ───────────────────────────────────────────────────────────
    if mode == "teacher":
        from standards_router import route_teacher
        from rag_ingestion import retrieve_with_metadata

        standards_result = route_teacher(context, free_text=user_input)

        # Short-circuit: return clarification question directly, no LLM call
        if standards_result.needs_clarification:
            metadata["clarification_returned"] = True
            metadata["retrieval_query"]   = None
            metadata["retrieved_chunks"]  = []
            metadata["target_lab"]        = standards_result.target_lab
            metadata["standards_result"]  = {
                "system":              "unknown",
                "stage":               "unknown",
                "confidence":          standards_result.confidence,
                "matched_labs":        [],
                "target_lab":          standards_result.target_lab,
                "needs_clarification": True,
            }
            return standards_result.fallback_script, metadata

        # Pre-retrieval: enforced in Python before LLM
        target_lab = standards_result.target_lab
        retrieval_query = (
            f"{target_lab} curriculum activities"
            if target_lab
            else f"{context.get('subject_area', '')} {context.get('current_unit', '')} climate lab"
        ).strip()

        retrieved_text, retrieved_chunks = retrieve_with_metadata(retrieval_query, k=5)

        metadata["retrieval_query"]   = retrieval_query
        metadata["retrieved_chunks"]  = retrieved_chunks
        metadata["target_lab"]        = target_lab
        metadata["standards_result"]  = {
            "system":             standards_result.curriculum_system,
            "stage":              standards_result.stage,
            "confidence":         standards_result.confidence,
            "matched_labs":       standards_result.matched_labs,
            "target_lab":         target_lab,
            "needs_clarification": False,
        }

        standards_block = standards_result.format_for_prompt()
        system_prompt   = _teacher_system_prompt(context, standards_block, retrieved_text)

    # ── STUDENT MODE ───────────────────────────────────────────────────────────
    elif mode == "student":
        from socratic_engine import select_questions
        from rag_ingestion import retrieve_with_metadata

        lab_name = context.get("lab_name", "")
        retrieval_query = f"{lab_name} student project activities" if lab_name else "student climate project activities"

        # Pre-retrieval: enforced in Python before LLM
        retrieved_text, retrieved_chunks = retrieve_with_metadata(retrieval_query, k=5)

        block = select_questions(
            message=user_input,
            phase=context.get("phase", "planning"),
            context=context,
            depth_level=min(1 + turn_count // 2, 3),
            used_question_ids=used_question_ids,
            turn_count=turn_count,
        )

        metadata["retrieval_query"]  = retrieval_query
        metadata["retrieved_chunks"] = retrieved_chunks
        metadata["socratic"] = {
            "signals":          block.detected_signals,
            "category":         block.primary_category,
            "question_id":      block.question_id,
            "primary_question": block.primary_question,
            "is_distressed":    block.is_distressed,
            "growth_reflection": block.growth_reflection,
        }

        system_prompt = _student_system_prompt(context, block.format_for_prompt(), retrieved_text)

    # ── MATH MODE ──────────────────────────────────────────────────────────────
    else:
        # Math mode: no mandatory pre-retrieval (EPA factors are hardcoded in prompt)
        # Supplemental tool available for En-ROADS guidance lookups
        system_prompt = _math_system_prompt(context)

    # ── LLM agent ──────────────────────────────────────────────────────────────
    llm   = _make_llm()
    tools = [_make_supplemental_rag_tool()]

    messages = [SystemMessage(content=system_prompt)]
    messages.extend(chat_history)
    messages.append(HumanMessage(content=user_input))

    agent  = create_react_agent(llm, tools)
    result = agent.invoke({"messages": messages})
    return _extract_output(result), metadata


# ── Prompt helpers exposed for test suite (no LLM calls) ──────────────────────

def _math_system_prompt_public(context: dict) -> str:
    return _math_system_prompt(context)


def _teacher_system_prompt_public(
    context: dict, standards_block: str, retrieved_context: str = ""
) -> str:
    return _teacher_system_prompt(context, standards_block, retrieved_context)


def _student_system_prompt_public(
    context: dict, socratic_block: str, retrieved_context: str = ""
) -> str:
    return _student_system_prompt(context, socratic_block, retrieved_context)


# ── Local smoke test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "teacher"

    contexts = {
        "teacher": {
            "subject_area": "Chemistry", "grade_band": "high school",
            "curriculum_standard": "NGSS", "current_unit": "Chemical reactions and energy",
            "country": "US", "school_type": "public",
        },
        "student": {
            "phase": "planning", "grade_band": "high school",
            "lab_name": "Renewable Energy",
            "project_description": "We want to put solar panels on the school",
        },
        "math": {
            "math_confidence": 2, "grade_band": "high school",
            "project_description": "Solar panels on school roof",
            "current_calculation_step": "electricity savings",
        },
    }
    inputs = {
        "teacher": "I teach AP Chemistry. How does the Renewable Energy lab fit into NGSS?",
        "student": "We just want to make a poster about solar panels. Is that okay?",
        "math": "I hate math. How do I calculate CO2 savings from switching to LED lights?",
    }

    print(f"\n=== Agent 1 — {mode_arg.upper()} MODE ===\n")
    response, meta = run_agent1(
        mode=mode_arg,
        user_input=inputs[mode_arg],
        context=contexts[mode_arg],
    )
    print(response)
    print("\n--- Metadata ---")
    print(json.dumps(meta, indent=2, default=str))

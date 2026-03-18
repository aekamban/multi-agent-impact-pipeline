"""
app.py — TCImpact Streamlit UI
Wires Agent 1 → 2 → 3 → 4 pipeline with a demo-ready interface.
Demo audience: Kate Keefer, TCI Director of Operations (non-technical).

Tabs:
  1. Teacher Mode  — full pipeline, shows structured intake + funder summary
  2. Student Mode  — Agent 1 only (Socratic coaching), anonymous
  3. Impact Dashboard — read-only view of last pipeline run
"""

import json
import os

import streamlit as st

# ─── Page config must be first Streamlit call ─────────────────────────────────
st.set_page_config(
    page_title="TCImpact",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
  }

  .tci-wordmark {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #1a4731;
    letter-spacing: -0.5px;
    margin: 0;
    line-height: 1;
  }
  .tci-tagline {
    font-size: 0.8rem;
    color: #6b8f71;
    font-weight: 300;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 2px;
  }

  .offline-banner {
    background: #fff8e1;
    border-left: 4px solid #f9a825;
    padding: 10px 16px;
    border-radius: 4px;
    font-size: 0.85rem;
    color: #5d4037;
    margin-bottom: 16px;
  }

  .agent-response {
    background: #f0f7f2;
    border-left: 4px solid #2e7d52;
    border-radius: 6px;
    padding: 18px 20px;
    font-size: 0.95rem;
    line-height: 1.7;
    color: #1c3a28;
    white-space: pre-wrap;
    margin-bottom: 8px;
  }

  .student-response {
    background: #f3f8f4;
    border-left: 4px solid #43a066;
    border-radius: 6px;
    padding: 18px 20px;
    font-size: 0.95rem;
    line-height: 1.7;
    color: #1c3a28;
    white-space: pre-wrap;
    margin-bottom: 8px;
  }

  .metric-pill {
    display: inline-block;
    background: #e8f5ec;
    border: 1px solid #b8ddc3;
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.8rem;
    color: #2e7d52;
    font-weight: 500;
    margin: 3px 4px 3px 0;
  }

  .section-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6b8f71;
    margin-bottom: 6px;
  }

  .privacy-note {
    background: #fafafa;
    border: 1px dashed #ccc;
    border-radius: 4px;
    padding: 10px 14px;
    font-size: 0.8rem;
    color: #888;
    margin-top: 8px;
  }

  button[data-baseweb="tab"] {
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
  }

  .funder-box {
    background: #1a4731;
    color: #d4edda;
    border-radius: 8px;
    padding: 20px 24px;
    font-size: 0.9rem;
    line-height: 1.75;
    white-space: pre-wrap;
  }

  .logic-box {
    background: #f9fbf9;
    border: 1px solid #c8dece;
    border-radius: 6px;
    padding: 16px 20px;
    font-size: 0.88rem;
    line-height: 1.65;
    color: #2a4a35;
    white-space: pre-wrap;
  }

  .json-box {
    background: #1e2a22;
    color: #7ec89a;
    border-radius: 6px;
    padding: 16px;
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    overflow-x: auto;
    white-space: pre;
  }

  .dash-card {
    background: white;
    border: 1px solid #ddeee3;
    border-radius: 8px;
    padding: 18px 20px;
    text-align: center;
  }
  .dash-card .value {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #1a4731;
    line-height: 1.1;
  }
  .dash-card .label {
    font-size: 0.75rem;
    color: #6b8f71;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 4px;
  }
</style>
""", unsafe_allow_html=True)


# ─── Jotform safe-display allowlist ──────────────────────────────────────────
# Only these keys from jotform_draft are shown in the UI.
# All personal data, media upload, and consent fields are hidden
# regardless of what agent4 writes — defence-in-depth on top of agent4's
# own JOTFORM_BLANK_FIELDS list.
# Keys are the exact Jotform column header strings from agent4.py constants.
_JF_OVERVIEW_KEY = (
    'Please give an overview of your project: (If you opt to instead record '
    'video or voice below, just type "Recorded.")'
)
_JF_HIGHLIGHTS_KEY = (
    "Please provide any highlights or student feedback from the project, "
    "including student quotes, reactions, challenges, or successes. "
    '(If you opt to instead record video or voice below, just type "Recorded.")'
)

JOTFORM_SAFE_KEYS: set = {
    "Submission Date",
    "Name of your school or institution:",
    "How many students completed your Action Project?",
    "Which Learning Lab(s) did you use?",
    "Which best captures your project's thematic topic?",
    _JF_OVERVIEW_KEY,
    _JF_HIGHLIGHTS_KEY,
}

JOTFORM_KEY_LABELS: dict = {
    "Submission Date": "Submission Date",
    "Name of your school or institution:": "School / Institution",
    "How many students completed your Action Project?": "Student Count",
    "Which Learning Lab(s) did you use?": "Learning Lab(s)",
    "Which best captures your project's thematic topic?": "Thematic Topic",
    _JF_OVERVIEW_KEY: "Project Overview",
    _JF_HIGHLIGHTS_KEY: "Highlights / Student Feedback",
}

_JOTFORM_FALLBACK_PRIVACY = (
    "Sensitive personal data (name, email, phone, address), student media, "
    "upload evidence, and consent must be completed directly in TCI's official "
    "Jotform for privacy compliance. This system does not collect or store them."
)


# ─── Helper: clean enum / value display ───────────────────────────────────────
def _display(value) -> str:
    """Return a clean human-readable string from an enum, bool, or plain value."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    # str enums have a .value attribute giving the raw string e.g. "high", "B"
    if hasattr(value, "value"):
        return str(value.value).replace("_", " ").title()
    return str(value)


# ─── Session state init ────────────────────────────────────────────────────────
if "pipeline_result" not in st.session_state:
    # Stores tuple: (agent1_resp: str, metadata: dict, raw_input: RawInput, state: ProjectState)
    st.session_state.pipeline_result = None
if "teacher_chat" not in st.session_state:
    st.session_state.teacher_chat = []       # list of (role: str, text: str)
if "student_chat" not in st.session_state:
    st.session_state.student_chat = []
if "student_used_q_ids" not in st.session_state:
    st.session_state.student_used_q_ids = []
if "student_turn_count" not in st.session_state:
    st.session_state.student_turn_count = 0

# ─── Live LLM detection ───────────────────────────────────────────────────────
LIVE_LLM = os.getenv("LIVE_LLM", "").strip() == "1"

# ─── Header ───────────────────────────────────────────────────────────────────
col_logo, _ = st.columns([3, 7])
with col_logo:
    st.markdown("""
    <p class="tci-wordmark">🌿 TCImpact</p>
    <p class="tci-tagline">The Climate Initiative · Learning Lab Companion</p>
    """, unsafe_allow_html=True)

st.markdown("---")

if not LIVE_LLM:
    st.markdown("""
    <div class="offline-banner">
      ⚠️ <strong>Offline mode</strong> — set <code>LIVE_LLM=1</code> to enable the AI assistant.
      Agents 2 → 4 (intake, impact calculation, funder summary) still run from your message text.
    </div>
    """, unsafe_allow_html=True)

# ─── Tabs ──────────────────────────────────────────────────────────────────────
tab_teacher, tab_student, tab_dashboard = st.tabs([
    "🏫  Teacher Mode",
    "🌱  Student Mode",
    "📊  Impact Dashboard",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — TEACHER MODE
# ══════════════════════════════════════════════════════════════════════════════
with tab_teacher:

    st.markdown("### Curriculum Integration Assistant")
    st.caption(
        "Describe your learning lab and project plans. "
        "The assistant will help align your lab to your curriculum standards "
        "and automatically structure your project data for year-end reporting."
    )

    # ── Context form ──────────────────────────────────────────────────────────
    with st.expander("⚙️  Your classroom context", expanded=not bool(st.session_state.pipeline_result)):
        ctx_col1, ctx_col2, ctx_col3 = st.columns(3)
        with ctx_col1:
            t_subject  = st.text_input("Subject area", value="Environmental Science", key="t_subject")
            t_standard = st.selectbox(
                "Curriculum standard",
                ["NGSS", "AP Environmental Science", "IB MYP", "IB DP ESS",
                 "UK GCSE", "Common Core", "State/Provincial", "Other"],
                key="t_standard",
            )
        with ctx_col2:
            t_school = st.text_input("School name (optional)", key="t_school")
            t_city   = st.text_input("City", key="t_city")
        with ctx_col3:
            t_state   = st.text_input("State / Province", key="t_state")
            t_country = st.text_input("Country", value="USA", key="t_country")
            t_title1  = st.checkbox("Title I school", key="t_title1")

    # Demo toggle: pass jotform_submitted=True to agent4 to unlock map export
    jotform_submitted_demo = st.checkbox(
        "📋  Preview as Jotform-submitted (unlocks Moore Foundation map export for demo)",
        value=False,
        key="jotform_submitted_demo",
    )

    # ── Chat history display ──────────────────────────────────────────────────
    for role, text in st.session_state.teacher_chat:
        if role == "user":
            st.chat_message("user").write(text)
        else:
            st.chat_message("assistant").markdown(
                f'<div class="agent-response">{text}</div>', unsafe_allow_html=True
            )

    st.markdown(
        '<div class="privacy-note">🔒 <strong>Privacy reminder:</strong> '
        "Please do not enter student names, photos, videos, email addresses, or home addresses. "
        "TCImpact drafts project reporting only — sensitive details and media should be submitted "
        "directly through TCI's official Jotform.</div>",
        unsafe_allow_html=True,
    )

    teacher_input = st.chat_input(
        "Describe your lab, your students, or your project idea…",
        key="teacher_chat_input",
    )

    if teacher_input:
        st.session_state.teacher_chat.append(("user", teacher_input))
        st.chat_message("user").write(teacher_input)

        # ── Build TeacherContext ──────────────────────────────────────────────
        # Verified against project_state.py:
        #   - NO grade_band field on TeacherContext (lives on StructuredIntake)
        #   - All str fields default to "" — pass "" not None for Pydantic safety
        #   - title1_status is a plain str: "yes" | "no" | "unknown"
        try:
            from project_state import TeacherContext, SchoolLocale, SchoolType
        except ImportError as e:
            st.error(
                f"❌ Could not import project_state: {e}\n\n"
                "Make sure project_state.py is in the same directory as app.py."
            )
            st.stop()

        teacher_ctx = TeacherContext(
            school_name=t_school or "",
            subject_area=t_subject or "",
            curriculum_standard=t_standard or "NGSS",
            city=t_city or "",
            state_province=t_state or "",
            country=t_country or "",
            school_locale=SchoolLocale.UNKNOWN,
            school_type=SchoolType.PUBLIC if t_title1 else SchoolType.UNKNOWN,
            title1_status="yes" if t_title1 else "no",
        )

        agent1_ctx = {
            "subject_area": t_subject,
            "curriculum_standard": t_standard,
            "school_name": t_school,
            "city": t_city,
            "country": t_country,
        }

        # ── Run pipeline ──────────────────────────────────────────────────────
        # run_agent1_to_4_pipeline returns: (str, dict, RawInput, ProjectState)
        with st.spinner("Thinking…"):
            try:
                from pipeline_agent1_to_4 import run_agent1_to_4_pipeline

                agent1_resp, metadata, raw_input, final_state = run_agent1_to_4_pipeline(
                    teacher_message=teacher_input,
                    mode="teacher",
                    agent1_context=agent1_ctx,
                    teacher_context=teacher_ctx,
                    chat_history=[
                        {"role": r, "content": t}
                        for r, t in st.session_state.teacher_chat[:-1]
                    ],
                    used_question_ids=[],
                    turn_count=len(st.session_state.teacher_chat),
                    jotform_submitted=jotform_submitted_demo,
                )
                st.session_state.pipeline_result = (agent1_resp, metadata, raw_input, final_state)

            except ImportError as e:
                st.error(
                    f"❌ Could not import pipeline: {e}\n\n"
                    "Check that pipeline_agent1_to_4.py and all agent files are present."
                )
                st.stop()
            except Exception as e:
                st.error(f"❌ Pipeline error: {e}")
                agent1_resp = (
                    "Something went wrong running the pipeline. "
                    "Check the error above — all agent files must be in the working directory."
                )
                final_state = None
                st.session_state.pipeline_result = None

        st.session_state.teacher_chat.append(("assistant", agent1_resp))
        st.chat_message("assistant").markdown(
            f'<div class="agent-response">{agent1_resp}</div>', unsafe_allow_html=True
        )

        # Clarification signal — surface before downstream panels
        if isinstance(metadata, dict) and metadata.get("clarification_returned"):
            st.info(
                "⚠️ We need a bit more detail to fully structure your project. "
                "You can still see a draft below — add more information in your next message to improve it."
            )

        # ── Downstream results ────────────────────────────────────────────────
        if final_state is not None:
            si  = getattr(final_state, "structured_intake", None)
            im  = getattr(final_state, "impact_metrics", None)
            rep = getattr(final_state, "reporting", None)

            # ── Structured Intake ─────────────────────────────────────────────
            if si is not None:
                with st.expander("🗂️  Structured intake — what was extracted from your message"):

                    conf = getattr(si, "lab_match_confidence", None)
                    if conf is not None and conf < 0.8:
                        st.warning(
                            f"⚠️ Lab name match confidence is low ({conf:.0%}). "
                            "Consider clarifying which TCI learning lab you used."
                        )

                    pills_html = ""
                    lab = getattr(si, "canonical_lab_name", None)
                    if lab:
                        pills_html += f'<span class="metric-pill">Lab: {lab}</span>'

                    track = getattr(si, "track", None)
                    if track is not None:
                        pills_html += f'<span class="metric-pill">Track {_display(track)}</span>'

                    students = getattr(si, "num_students_estimate", None)
                    if students is not None:             # explicit None check — 0 is valid
                        pills_html += f'<span class="metric-pill">~{students} students</span>'

                    ptype = getattr(si, "project_type", None)
                    if ptype:
                        pills_html += f'<span class="metric-pill">{ptype}</span>'

                    grade = getattr(si, "grade_band", None)
                    if grade is not None:
                        pills_html += f'<span class="metric-pill">{_display(grade)}</span>'

                    if getattr(si, "equity_flag", None) is True:
                        pills_html += '<span class="metric-pill">Equity-flagged ✓</span>'

                    if getattr(si, "sustained_action", None) is True:
                        pills_html += '<span class="metric-pill">Sustained action ✓</span>'

                    if pills_html:
                        st.markdown(pills_html, unsafe_allow_html=True)
                    else:
                        st.caption("No structured fields extracted yet — share more details about your lab and project.")

                    partners = getattr(si, "community_partnerships", [])
                    if partners:
                        st.markdown("**Community partners identified:**")
                        for p in partners:
                            pname    = getattr(p, "name", "")
                            ptype_str = getattr(p, "partner_type", "")
                            label = f"{pname} ({ptype_str})" if ptype_str else pname
                            st.markdown(f"- {label}")

            # ── Impact metrics ────────────────────────────────────────────────
            if im is not None:
                with st.expander("📈  Impact metrics"):
                    m_col1, m_col2, m_col3 = st.columns(3)
                    with m_col1:
                        reach = getattr(im, "reach_estimate", None)
                        if reach is not None:
                            st.metric("People reached", f"{reach:,}")
                    with m_col2:
                        co2 = getattr(im, "co2_reduction_lbs", None)
                        if co2 is not None:
                            st.metric("CO₂ reduction (lbs)", f"{co2:,.0f}")
                    with m_col3:
                        comm = getattr(im, "community_score_total", None)
                        if comm is not None:
                            st.metric("Community score", f"{comm:.1f}/10")

                    method = getattr(im, "methodology_notes", "")
                    if method:
                        st.caption(f"Methodology: {method}")

            # ── Funder summary ────────────────────────────────────────────────
            if rep is not None:
                fs = getattr(rep, "funder_summary", "")
                if fs:
                    st.markdown('<p class="section-label">Funder summary</p>', unsafe_allow_html=True)
                    st.markdown(f'<div class="funder-box">{fs}</div>', unsafe_allow_html=True)

                lm_text = getattr(rep, "logic_model_text", "")
                if lm_text:
                    with st.expander("🔗  Logic model"):
                        st.markdown(f'<div class="logic-box">{lm_text}</div>', unsafe_allow_html=True)

                # ── Jotform draft — explicit allowlist rendering ───────────────
                jd = getattr(rep, "jotform_draft", None)
                if jd:
                    with st.expander("📝  Jotform draft — review before submitting to TCI"):
                        st.info(
                            "This draft was auto-generated from your conversations this year. "
                            "Review each field, then complete your official submission at TCI's Jotform link. "
                            "**Fields marked ✏️ must be completed directly in the official form.**"
                        )
                        if isinstance(jd, dict):
                            rendered_any = False
                            for key in JOTFORM_SAFE_KEYS:
                                value = jd.get(key, "")
                                if value:
                                    label = JOTFORM_KEY_LABELS.get(key, key)
                                    st.markdown(f"**{label}**")
                                    st.write(value)
                                    st.markdown("---")
                                    rendered_any = True
                            if not rendered_any:
                                st.caption(
                                    "Draft fields will populate as you share more details "
                                    "about your project throughout the year."
                                )
                            privacy_note = jd.get("_privacy_note", "") or _JOTFORM_FALLBACK_PRIVACY
                            blank_fields = jd.get("_blank_fields", [])
                            omitted_labels = []
                            if blank_fields:
                                _OMIT_LABELS = {
                                    "Name": "Teacher name",
                                    "Email": "Email address",
                                    "Phone Number": "Phone number",
                                    "Mailing address, for shipping your free TCI merch:": "Mailing address",
                                    "By submitting this form, you agree that TCI can use this material for promotion, marketing, and dissemination.": "Consent declaration",
                                }
                                for bf in blank_fields:
                                    label = _OMIT_LABELS.get(bf) or (bf[:60] + "…" if len(bf) > 60 else bf)
                                    omitted_labels.append(label)
                            st.markdown(
                                f'<div class="privacy-note">🔒 {privacy_note}'
                                + (
                                    "<br><strong>Intentionally omitted (complete in official Jotform):</strong> "
                                    + ", ".join(omitted_labels)
                                    if omitted_labels else ""
                                )
                                + "</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.write(str(jd))

                # ── Map export ────────────────────────────────────────────────
                map_json = getattr(rep, "map_export_json", None)
                with st.expander("🗺️  Moore Foundation map export"):
                    if map_json:
                        st.markdown(
                            f'<div class="json-box">{json.dumps(map_json, indent=2)}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div class="privacy-note">'
                            'Map export JSON is generated once the teacher submits their official Jotform. '
                            'Use the <strong>Preview as Jotform-submitted</strong> toggle above '
                            'to see what this export will look like.'
                            '</div>',
                            unsafe_allow_html=True,
                        )

            # ── Pipeline warnings ─────────────────────────────────────────────
            warnings = getattr(final_state, "warnings", [])
            if warnings:
                with st.expander(f"⚠️  {len(warnings)} pipeline warning(s)"):
                    for w in warnings:
                        st.warning(w)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — STUDENT MODE
# ══════════════════════════════════════════════════════════════════════════════
with tab_student:

    st.markdown("### Student Project Coach")
    st.caption(
        "Ask questions about your climate action project. "
        "No names are collected — your conversations are anonymous."
    )

    with st.expander("📋  Your project context", expanded=not bool(st.session_state.student_chat)):
        s_col1, s_col2 = st.columns(2)
        with s_col1:
            s_lab = st.selectbox(
                "Which learning lab?",
                ["Agriculture & Climate Change", "Civics Climate Action",
                 "Climate Justice and Equity", "Renewable Energy",
                 "Climate Impacts with En-ROADS", "Wildfires",
                 "Floods & Droughts", "Sea Level Rise", "Invasive Species",
                 "Climate & Health", "Climate Migration", "Not sure yet"],
                key="s_lab",
            )
            s_phase = st.selectbox(
                "Where are you in your project?",
                ["Planning", "Implementing", "Analyzing & Reporting"],
                key="s_phase",
            )
        with s_col2:
            s_desc = st.text_area(
                "What's your project about so far? (optional)",
                placeholder="e.g. We want to start a school composting program and track food waste…",
                height=100,
                key="s_desc",
            )

    # Chat history
    for role, text in st.session_state.student_chat:
        if role == "user":
            st.chat_message("user").write(text)
        else:
            st.chat_message("assistant").markdown(
                f'<div class="student-response">{text}</div>', unsafe_allow_html=True
            )

    student_input = st.chat_input(
        "What's on your mind about your project?",
        key="student_chat_input",
    )

    if student_input:
        st.session_state.student_chat.append(("user", student_input))
        st.chat_message("user").write(student_input)

        if not LIVE_LLM:
            response = (
                "The AI coach is currently in offline mode. "
                "Ask your teacher to enable it, or try again when LIVE_LLM=1 is set."
            )
        else:
            with st.spinner("Thinking…"):
                try:
                    from agent1 import run_agent1

                    phase_map = {
                        "Planning": "planning",
                        "Implementing": "implementing",
                        "Analyzing & Reporting": "analyzing",
                    }
                    student_ctx = {
                        "lab_name": s_lab,
                        "project_description": s_desc,
                        "phase": phase_map.get(s_phase, "planning"),
                    }
                    response, _meta = run_agent1(
                        mode="student",
                        user_input=student_input,
                        context=student_ctx,
                        chat_history=[
                            {"role": r, "content": t}
                            for r, t in st.session_state.student_chat[:-1]
                        ],
                        used_question_ids=st.session_state.student_used_q_ids,
                        turn_count=st.session_state.student_turn_count,
                    )
                    st.session_state.student_turn_count += 1

                    # Deduplicate used_question_ids — across turns AND within the same turn's batch
                    if isinstance(_meta, dict):
                        new_ids = _meta.get("used_question_ids", [])
                        if new_ids:
                            existing = set(st.session_state.student_used_q_ids)
                            seen_this_turn: set = set()
                            for q in new_ids:
                                if q not in existing and q not in seen_this_turn:
                                    st.session_state.student_used_q_ids.append(q)
                                    seen_this_turn.add(q)

                except ImportError as e:
                    response = (
                        f"❌ Could not load the student coach: {e}\n\n"
                        "Make sure agent1.py is in the same directory as app.py."
                    )
                except Exception as e:
                    response = (
                        f"Something went wrong with the student coach: {e}\n\n"
                        "Please check that agent1.py is available and LIVE_LLM=1 is set."
                    )

        st.session_state.student_chat.append(("assistant", response))
        st.chat_message("assistant").markdown(
            f'<div class="student-response">{response}</div>', unsafe_allow_html=True
        )

    st.markdown("""
    <div class="privacy-note" style="margin-top:24px;">
      🔒 <strong>Student privacy:</strong> No names, emails, or personally identifying information
      are collected in student mode. Conversations are anonymous by design.
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — IMPACT DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tab_dashboard:

    st.markdown("### Impact Dashboard")
    st.caption("Read-only view of the most recent pipeline run.")

    result = st.session_state.pipeline_result

    if result is None:
        st.info(
            "No pipeline run yet. Go to **Teacher Mode**, describe your learning lab, "
            "and submit a message to populate this dashboard."
        )
    else:
        _resp, _meta, raw_input, final_state = result

        if final_state is None:
            st.warning("Pipeline ran but did not produce a final state. Check the Teacher Mode tab for errors.")
        else:
            si  = getattr(final_state, "structured_intake", None)
            im  = getattr(final_state, "impact_metrics", None)
            rep = getattr(final_state, "reporting", None)

            # ── Top metrics row ───────────────────────────────────────────────
            d_col1, d_col2, d_col3, d_col4 = st.columns(4)

            with d_col1:
                lab_name = (getattr(si, "canonical_lab_name", None) or "—") if si else "—"
                st.markdown(
                    f'<div class="dash-card"><div class="value" style="font-size:1.1rem">{lab_name}</div>'
                    f'<div class="label">Learning Lab</div></div>',
                    unsafe_allow_html=True,
                )

            with d_col2:
                track_val = getattr(si, "track", None) if si else None
                track_display = f"Track {_display(track_val)}" if track_val is not None else "—"
                st.markdown(
                    f'<div class="dash-card"><div class="value">{track_display}</div>'
                    f'<div class="label">Project Track</div></div>',
                    unsafe_allow_html=True,
                )

            with d_col3:
                students = getattr(si, "num_students_estimate", None) if si else None
                students_display = f"{students:,}" if students is not None else "—"
                st.markdown(
                    f'<div class="dash-card"><div class="value">{students_display}</div>'
                    f'<div class="label">Students</div></div>',
                    unsafe_allow_html=True,
                )

            with d_col4:
                co2   = getattr(im, "co2_reduction_lbs", None) if im else None
                reach = getattr(im, "reach_estimate", None) if im else None
                if co2 is not None:
                    metric_v, metric_l = f"{co2:,.0f} lbs", "CO₂ Reduction"
                elif reach is not None:
                    metric_v, metric_l = f"{reach:,}", "People Reached"
                else:
                    metric_v, metric_l = "—", "Impact Metric"
                st.markdown(
                    f'<div class="dash-card"><div class="value" style="font-size:1.4rem">{metric_v}</div>'
                    f'<div class="label">{metric_l}</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)

            if rep is not None:
                fs = getattr(rep, "funder_summary", "")
                if fs:
                    st.markdown('<p class="section-label">Funder Summary</p>', unsafe_allow_html=True)
                    st.markdown(f'<div class="funder-box">{fs}</div>', unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                lm_text = getattr(rep, "logic_model_text", "")
                if lm_text:
                    st.markdown('<p class="section-label">Logic Model</p>', unsafe_allow_html=True)
                    st.markdown(f'<div class="logic-box">{lm_text}</div>', unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                map_json = getattr(rep, "map_export_json", None)
                st.markdown('<p class="section-label">Moore Foundation Map Export</p>', unsafe_allow_html=True)
                if map_json:
                    st.markdown(
                        f'<div class="json-box">{json.dumps(map_json, indent=2)}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="privacy-note">Map export JSON is generated after the teacher '
                        'submits their official Jotform. Enable the <strong>Preview as Jotform-submitted</strong> '
                        'toggle in Teacher Mode and re-submit to see it here.</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No reporting data available in this pipeline run.")

            if raw_input is not None:
                with st.expander("🔍  Raw input received by Agent 2"):
                    try:
                        raw_dict = raw_input.model_dump()
                    except AttributeError:
                        raw_dict = vars(raw_input) if hasattr(raw_input, "__dict__") else str(raw_input)
                    st.json(raw_dict)

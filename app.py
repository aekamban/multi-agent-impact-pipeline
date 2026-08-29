"""
app.py — Streamlit UI
Wires Agent 1 → 2 → 3 → 4 pipeline with a demo-ready interface.
Demo audience: the organization's Director of Operations (non-technical).

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
    page_title="Impact Companion",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS — brand system, light theme ───────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  /* ── Page background — targeted, not global ── */
  [data-testid="stApp"],
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"],
  .main,
  .block-container {
    background-color: #FFFFFF !important;
  }

  .block-container {
    padding-top: 3rem !important;
    padding-bottom: 4rem !important;
    max-width: 1100px !important;
  }

  section[data-testid="stSidebar"] { display: none; }

  /* ── Typography — scoped to markdown content only, not all elements ── */
  /* DO NOT apply font-family to span/div/li globally — breaks Material icon ligatures */
  .stMarkdown,
  .stMarkdown p,
  [data-testid="stCaptionContainer"] p,
  h1, h2, h3, h4 {
    font-family: 'Inter', sans-serif !important;
    color: #1A1A1A !important;
  }

  [data-testid="stCaptionContainer"] p { color: #4A4A4A !important; font-size: 0.85rem !important; }

  /* ── Header accent band ── */
  [data-testid="stHeader"] { background-color: #FFFFFF !important; border-bottom: 1px solid #E5E7EB !important; }

  /* ── Wordmark ── */
  .impact-wordmark {
    font-family: 'Inter', sans-serif;
    font-size: 1.5rem; font-weight: 700; color: #2F7F84;
    letter-spacing: -0.3px; margin: 0; line-height: 1.2;
    padding-top: 4px;
  }
  .impact-tagline {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem; color: #6B7280; font-weight: 400;
    letter-spacing: 0.1em; text-transform: uppercase; margin-top: 4px;
  }

  /* ── Offline banner ── */
  .offline-banner {
    background: #FFFBEB; border-left: 4px solid #F59E0B;
    padding: 10px 16px; border-radius: 8px;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem; color: #92400E; margin-bottom: 16px;
  }

  /* ── Tabs — teal accent ── */
  button[data-baseweb="tab"] {
    font-weight: 500 !important;
    font-size: 0.9rem !important;
    color: #4A4A4A !important;
  }
  button[data-baseweb="tab"][aria-selected="true"] {
    color: #2F7F84 !important;
    font-weight: 600 !important;
  }
  [data-testid="stTabs"] [role="tablist"] {
    border-bottom: 2px solid #E5E7EB !important;
  }

  /* ── Input fields — white with visible border ── */
  [data-testid="stTextInput"] input {
    background-color: #FFFFFF !important;
    color: #1A1A1A !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
  }
  [data-testid="stTextArea"] textarea {
    background-color: #FFFFFF !important;
    color: #1A1A1A !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
  }
  [data-testid="stSelectbox"] > div > div {
    background-color: #FFFFFF !important;
    color: #1A1A1A !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 6px !important;
  }

  /* ── Expanders — white cards with green left accent ── */
  /* Scoped ONLY to the container, NOT to summary text to avoid icon ligature bugs */
  [data-testid="stExpander"] {
    background-color: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    margin-bottom: 8px !important;
  }
  /* Expander header background only — do NOT set font-family here */
  details > summary {
    background-color: #FFFFFF !important;
    border-radius: 8px !important;
    padding: 4px 0 !important;
  }
  details[open] > summary {
    border-bottom: 1px solid #F3F4F6 !important;
  }

  /* ── Metrics — teal values ── */
  [data-testid="stMetricValue"]  { color: #2F7F84 !important; font-weight: 600 !important; }
  [data-testid="stMetric"] label { color: #4A4A4A !important; font-size: 0.8rem !important; }

  /* ── Alert boxes ── */
  [data-testid="stAlert"] { border-radius: 8px !important; }

  /* ── Chat input ── */
  [data-testid="stChatInput"] textarea {
    background-color: #FFFFFF !important;
    color: #1A1A1A !important;
    border: 1px solid #D1D5DB !important;
    font-family: 'Inter', sans-serif !important;
  }

  /* ── Divider ── */
  hr { border-color: #E5E7EB !important; margin: 32px 0 !important; }

  /* ═══════════════════════════════════════════
     CUSTOM CONTENT COMPONENTS
  ═══════════════════════════════════════════ */

  /* ── Section labels — green rule above ── */
  .section-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: #2F7F84;
    border-top: 2px solid #6BA539;
    padding-top: 16px; margin-bottom: 16px; margin-top: 40px;
    display: block;
  }

  /* ── Privacy note — pale teal tint ── */
  .privacy-note {
    font-family: 'Inter', sans-serif;
    background: #F0F9FA; border: 1px solid #C5DFE1; border-radius: 8px;
    padding: 12px 16px; font-size: 0.8rem; color: #374151;
    margin-top: 16px; line-height: 1.6;
  }

  /* ── User message — right-aligned feel, light gray ── */
  .user-message {
    font-family: 'Inter', sans-serif;
    background: #F3F4F6; border: 1px solid #E5E7EB;
    border-radius: 10px 10px 2px 10px;
    padding: 14px 18px; font-size: 0.9rem; line-height: 1.65;
    color: #1A1A1A; margin: 8px 0 8px 10%;
  }

  /* ── Assistant response — green left accent ── */
  .agent-response {
    font-family: 'Inter', sans-serif;
    background: #FFFFFF; border: 1px solid #E5E7EB;
    border-left: 4px solid #6BA539; border-radius: 2px 10px 10px 2px;
    padding: 20px 24px; font-size: 0.9rem; line-height: 1.75;
    color: #1A1A1A; white-space: pre-wrap; margin: 8px 0;
  }

  /* ── Student response — teal left accent ── */
  .student-response {
    font-family: 'Inter', sans-serif;
    background: #FFFFFF; border: 1px solid #C5DFE1;
    border-left: 4px solid #2F7F84; border-radius: 2px 10px 10px 2px;
    padding: 20px 24px; font-size: 0.9rem; line-height: 1.75;
    color: #1A1A1A; white-space: pre-wrap; margin: 8px 0;
  }

  /* ── Intake pills — teal tone ── */
  .metric-pill {
    font-family: 'Inter', sans-serif;
    display: inline-block; background: #E6F2F3;
    border: 1px solid #A8D1D4; border-radius: 999px;
    padding: 4px 14px; font-size: 0.78rem; color: #1D6B70;
    font-weight: 500; margin: 3px 4px 3px 0;
  }

  /* ── Funder summary — teal box ── */
  .funder-box {
    font-family: 'Inter', sans-serif;
    background: #2F7F84; color: #FFFFFF; border-radius: 12px;
    padding: 24px 28px; font-size: 0.92rem; line-height: 1.8;
    white-space: pre-wrap;
  }

  /* ── Logic model ── */
  .logic-box {
    font-family: 'Inter', sans-serif;
    background: #FAFAFA; border: 1px solid #E5E7EB;
    border-left: 3px solid #6BA539;
    border-radius: 4px 8px 8px 4px;
    padding: 20px 24px; font-size: 0.85rem; line-height: 1.75;
    color: #1A1A1A; white-space: pre-wrap;
  }

  /* ── Map export / JSON ── */
  .json-box {
    font-family: 'Courier New', monospace;
    background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 8px;
    padding: 20px 24px; font-size: 0.8rem; color: #1A1A1A;
    overflow-x: auto; white-space: pre;
  }

  /* ── Dashboard metric cards ── */
  .dash-card {
    background: #FFFFFF; border: 1px solid #E5E7EB;
    border-top: 3px solid #2F7F84;
    border-radius: 8px; padding: 20px 24px; text-align: center;
  }
  .dash-card .value {
    font-family: 'Inter', sans-serif;
    font-size: 2.2rem; font-weight: 600; color: #2F7F84; line-height: 1.1;
  }
  .dash-card .label {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem; font-weight: 600; color: #6B7280;
    text-transform: uppercase; letter-spacing: 0.1em; margin-top: 6px;
  }

  /* ── Jotform field display ── */
  .jf-field-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem; font-weight: 700; color: #2F7F84;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 4px; margin-top: 20px;
  }
  .jf-field-value {
    font-family: 'Inter', sans-serif;
    font-size: 0.9rem; color: #1A1A1A; line-height: 1.6;
    padding-bottom: 16px; border-bottom: 1px solid #F3F4F6;
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
    "upload evidence, and consent must be completed directly in the organization's official "
    "Jotform for privacy compliance. This system does not collect or store them."
)


# ─── Helper: clean enum / value display ───────────────────────────────────────
def _display(value) -> str:
    """Return a clean human-readable string from an enum, bool, or plain value."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if hasattr(value, "value"):
        return str(value.value).replace("_", " ").title()
    return str(value)


def _clean_map_json(map_json: dict) -> dict:
    """Normalize enum reprs to plain strings for JSON display (e.g. GradeBand.HIGH → 'high')."""
    clean = {}
    for k, v in map_json.items():
        if hasattr(v, "value"):
            clean[k] = v.value
        elif isinstance(v, str) and "." in v and v.split(".")[0][:1].isupper():
            clean[k] = v.split(".")[-1].lower()
        else:
            clean[k] = v
    return clean


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
    <p class="impact-wordmark">Impact Companion</p>
    <p class="impact-tagline">Climate Education Program Companion</p>
    """, unsafe_allow_html=True)

st.markdown("---")

if not LIVE_LLM:
    st.markdown("""
    <div class="offline-banner">
      <strong>Note:</strong> The AI assistant is currently offline. Structured outputs (intake, impact metrics, reporting) will still generate from your message text. Set <code>LIVE_LLM=1</code> to enable the full AI experience.
    </div>
    """, unsafe_allow_html=True)

# ─── Tabs ──────────────────────────────────────────────────────────────────────
tab_teacher, tab_student, tab_dashboard = st.tabs([
    "Teacher Mode",
    "Student Mode",
    "Impact Dashboard",
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
    with st.expander("Your classroom context", expanded=not bool(st.session_state.pipeline_result)):
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
        "Preview as Jotform-submitted (unlocks the public impact map export for demo)",
        value=False,
        key="jotform_submitted_demo",
    )

    # ── Chat history display ──────────────────────────────────────────────────
    for role, text in st.session_state.teacher_chat:
        if role == "user":
            st.markdown(f'<div class="user-message">{text}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="agent-response">{text}</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="privacy-note"><strong>Privacy:</strong> '
        "Please do not include student names, photos, videos, email addresses, or home addresses. "
        "This tool is designed for project reporting only. Personal details and media should be submitted directly through the organization's official Jotform.</div>",
        unsafe_allow_html=True,
    )

    teacher_input = st.chat_input(
        "Describe your lab, your students, or your project idea…",
        key="teacher_chat_input",
    )

    if teacher_input:
        st.session_state.teacher_chat.append(("user", teacher_input))
        st.markdown(f'<div class="user-message">{teacher_input}</div>', unsafe_allow_html=True)

        # ── Build TeacherContext ──────────────────────────────────────────────
        # Verified against project_state.py:
        #   - NO grade_band field on TeacherContext (lives on StructuredIntake)
        #   - All str fields default to "" — pass "" not None for Pydantic safety
        #   - title1_status is a plain str: "yes" | "no" | "unknown"
        try:
            from project_state import TeacherContext, SchoolLocale, SchoolType
        except ImportError as e:
            st.error(
                f"Could not import project_state: {e}\n\n"
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
                    f"Could not import pipeline: {e}\n\n"
                    "Check that pipeline_agent1_to_4.py and all agent files are present."
                )
                st.stop()
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                agent1_resp = (
                    "Something went wrong running the pipeline. "
                    "Check the error above — all agent files must be in the working directory."
                )
                final_state = None
                st.session_state.pipeline_result = None

        st.session_state.teacher_chat.append(("assistant", agent1_resp))
        st.markdown(f'<div class="agent-response">{agent1_resp}</div>', unsafe_allow_html=True)

        # Clarification signal — surface before downstream panels
        if isinstance(metadata, dict) and metadata.get("clarification_returned"):
            st.info(
                "To generate your project summary, we need a few more details. "
                "You can still see a draft below — add more information in your next message to improve it."
            )

        # ── Downstream results ────────────────────────────────────────────────
        if final_state is not None:
            si  = getattr(final_state, "structured_intake", None)
            im  = getattr(final_state, "impact_metrics", None)
            rep = getattr(final_state, "reporting", None)

            # ════════════════════════════════════════════
            # SECTION A — CURRICULUM SUPPORT
            # (Agent 1 response already shown above in chat)
            # ════════════════════════════════════════════

            # ════════════════════════════════════════════
            # SECTION B — PROJECT IMPACT
            # ════════════════════════════════════════════
            st.markdown('<p class="section-label">Your Project</p>', unsafe_allow_html=True)

            # What we understood
            if si is not None:
                with st.expander("What we understood from your project", expanded=True):
                    conf = getattr(si, "lab_match_confidence", None)
                    if conf is not None and conf < 0.8:
                        st.warning(
                            f"We had difficulty matching your learning lab name (confidence: {conf:.0%}). "
                            "Consider clarifying which learning lab you are running."
                        )

                    pills_html = ""
                    lab = getattr(si, "canonical_lab_name", None)
                    if lab:
                        pills_html += f'<span class="metric-pill">Lab: {lab}</span>'

                    track = getattr(si, "track", None)
                    if track is not None:
                        pills_html += f'<span class="metric-pill">Track {_display(track)}</span>'

                    students = getattr(si, "num_students_estimate", None)
                    if students is not None:
                        pills_html += f'<span class="metric-pill">{students} students</span>'

                    ptype = getattr(si, "project_type", None)
                    if ptype:
                        pills_html += f'<span class="metric-pill">{ptype}</span>'

                    grade = getattr(si, "grade_band", None)
                    if grade is not None:
                        pills_html += f'<span class="metric-pill">{_display(grade)}</span>'

                    if getattr(si, "equity_flag", None) is True:
                        pills_html += '<span class="metric-pill">Equity focus</span>'

                    if getattr(si, "sustained_action", None) is True:
                        pills_html += '<span class="metric-pill">Sustained action</span>'

                    if pills_html:
                        st.markdown(pills_html, unsafe_allow_html=True)
                    else:
                        st.caption("Share more details about your lab and project to see a summary here.")

                    partners = getattr(si, "community_partnerships", [])
                    if partners:
                        st.markdown("<br>**Community partners identified:**", unsafe_allow_html=True)
                        for p in partners:
                            pname     = getattr(p, "name", "")
                            ptype_str = getattr(p, "partner_type", "")
                            label = f"{pname} ({ptype_str})" if ptype_str else pname
                            st.markdown(f"- {label}")

            # Impact metrics
            if im is not None:
                with st.expander("Project impact", expanded=True):
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
                            st.metric("Community score", f"{comm:.1f}/100")

                    method = getattr(im, "methodology_notes", "")
                    if method:
                        st.caption(method)

            # ════════════════════════════════════════════
            # SECTION C — REPORTING AND EXPORTS
            # ════════════════════════════════════════════
            if rep is not None:
                st.markdown('<p class="section-label">Reporting and Exports</p>', unsafe_allow_html=True)

                fs = getattr(rep, "funder_summary", "")
                if fs:
                    st.markdown(f'<div class="funder-box">{fs}</div>', unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                lm_text = getattr(rep, "logic_model_text", "")
                if lm_text:
                    with st.expander("Logic model", expanded=False):
                        st.markdown(f'<div class="logic-box">{lm_text}</div>', unsafe_allow_html=True)

                jd = getattr(rep, "jotform_draft", None)
                if jd:
                    with st.expander("Jotform submission draft", expanded=False):
                        st.caption(
                            "This draft was prepared from your project information. "
                            "Review each field, then complete your official submission at the organization's Jotform link. "
                            "Personal details, photos, and consent must be added directly in the official form."
                        )
                        if isinstance(jd, dict):
                            rendered_any = False
                            for key in JOTFORM_SAFE_KEYS:
                                value = jd.get(key, "")
                                if value:
                                    label = JOTFORM_KEY_LABELS.get(key, key)
                                    st.markdown(
                                        f'<p class="jf-field-label">{label}</p>'
                                        f'<p class="jf-field-value">{value}</p>',
                                        unsafe_allow_html=True,
                                    )
                                    rendered_any = True
                            if not rendered_any:
                                st.caption(
                                    "Draft fields will fill in as you share more about your project."
                                )
                            privacy_note = jd.get("_privacy_note", "") or _JOTFORM_FALLBACK_PRIVACY
                            blank_fields = jd.get("_blank_fields", [])
                            omitted_labels = []
                            if blank_fields:
                                _OMIT_LABELS = {
                                    "Name": "Teacher name",
                                    "Email": "Email address",
                                    "Phone Number": "Phone number",
                                    "Mailing address, for shipping your free program merchandise:": "Mailing address",
                                    "By submitting this form, you agree that the organization can use this material for promotion, marketing, and dissemination.": "Consent declaration",
                                }
                                for bf in blank_fields:
                                    lbl = _OMIT_LABELS.get(bf) or (bf[:60] + "…" if len(bf) > 60 else bf)
                                    omitted_labels.append(lbl)
                            st.markdown(
                                f'<div class="privacy-note">{privacy_note}'
                                + (
                                    "<br><strong>Complete in official Jotform:</strong> "
                                    + ", ".join(omitted_labels)
                                    if omitted_labels else ""
                                )
                                + "</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.write(str(jd))

                map_json = getattr(rep, "map_export_json", None)
                with st.expander("Map-ready data export", expanded=False):
                    if map_json:
                        st.markdown(
                            f'<div class="json-box">{json.dumps(_clean_map_json(map_json), indent=2)}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div class="privacy-note">'
                            'Map data is generated once you submit your official Jotform. '
                            'Use the toggle above to preview what this will look like.'
                            '</div>',
                            unsafe_allow_html=True,
                        )

            # Technical details — tucked away for demo
            tech_items = []
            warnings = getattr(final_state, "warnings", [])
            raw_input = getattr(final_state, "raw_input", None)

            if warnings or raw_input:
                with st.expander("Technical details (demo only)", expanded=False):
                    if warnings:
                        for w in warnings:
                            st.caption(f"Note: {w}")
                    if raw_input is not None:
                        try:
                            raw_dict = raw_input.model_dump()
                        except AttributeError:
                            raw_dict = vars(raw_input) if hasattr(raw_input, "__dict__") else str(raw_input)
                        st.json(raw_dict)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — STUDENT MODE
# ══════════════════════════════════════════════════════════════════════════════
with tab_student:

    st.markdown("### Student Project Coach")
    st.caption(
        "Ask questions about your climate action project. "
        "No names are collected — your conversations are anonymous."
    )

    with st.expander("Your project context", expanded=not bool(st.session_state.student_chat)):
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
            st.markdown(f'<div class="user-message">{text}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="student-response">{text}</div>', unsafe_allow_html=True)

    student_input = st.chat_input(
        "What's on your mind about your project?",
        key="student_chat_input",
    )

    if student_input:
        st.session_state.student_chat.append(("user", student_input))
        st.markdown(f'<div class="user-message">{student_input}</div>', unsafe_allow_html=True)

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
                        f"The student coach could not be loaded: {e}\n\n"
                        "Make sure agent1.py is in the same directory as app.py."
                    )
                except Exception as e:
                    response = (
                        f"Something went wrong: {e}\n\n"
                        "Please check that agent1.py is available and LIVE_LLM=1 is set."
                    )

        st.session_state.student_chat.append(("assistant", response))
        st.markdown(f'<div class="student-response">{response}</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="privacy-note" style="margin-top:24px;">
      <strong>Student privacy:</strong> No names, emails, or personally identifying information
      are collected in student mode. All conversations are anonymous.
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — IMPACT DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tab_dashboard:

    st.markdown("### Impact Dashboard")
    st.caption("A summary of the most recent project run.")

    result = st.session_state.pipeline_result

    if result is None:
        st.info(
            "No project data yet. Go to Teacher Mode, describe your learning lab, "
            "and submit a message to populate this dashboard."
        )
    else:
        _resp, _meta, raw_input, final_state = result

        if final_state is None:
            st.warning("Something went wrong with the last run. Please try again in Teacher Mode.")
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
                    metric_v, metric_l = "—", "Impact"
                st.markdown(
                    f'<div class="dash-card"><div class="value" style="font-size:1.4rem">{metric_v}</div>'
                    f'<div class="label">{metric_l}</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)

            if rep is not None:
                # Funder summary — most prominent
                fs = getattr(rep, "funder_summary", "")
                if fs:
                    st.markdown('<p class="section-label">Summary for Reporting and Grants</p>', unsafe_allow_html=True)
                    st.markdown(f'<div class="funder-box">{fs}</div>', unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                lm_text = getattr(rep, "logic_model_text", "")
                if lm_text:
                    with st.expander("Logic model", expanded=False):
                        st.markdown(f'<div class="logic-box">{lm_text}</div>', unsafe_allow_html=True)

                # Map export — lower visual priority
                map_json = getattr(rep, "map_export_json", None)
                with st.expander("Map-ready data export", expanded=False):
                    if map_json:
                        st.markdown(
                            f'<div class="json-box">{json.dumps(_clean_map_json(map_json), indent=2)}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div class="privacy-note">Map data is generated after the official Jotform is submitted. '
                            'Use the toggle in Teacher Mode to preview what this will look like.</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No reporting data available for this project.")

            # Technical details — collapsed by default
            with st.expander("Technical details (demo only)", expanded=False):
                if raw_input is not None:
                    try:
                        raw_dict = raw_input.model_dump()
                    except AttributeError:
                        raw_dict = vars(raw_input) if hasattr(raw_input, "__dict__") else str(raw_input)
                    st.json(raw_dict)
                else:
                    st.caption("No raw input available.")

"""
TCImpact Database Layer
Handles all SQLite interactions for the POC.
No ORM — plain sqlite3 for simplicity and portability.
"""

import sqlite3
import hashlib
import json
import os
from datetime import datetime, date
from typing import Optional

DB_PATH = os.getenv("TCIMPACT_DB_PATH", "tcimpact.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


# ─────────────────────────────────────────
# CONNECTION & INITIALIZATION
# ─────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_db() -> None:
    """Create all tables from schema.sql if they don't already exist."""
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


# ─────────────────────────────────────────
# PRIVACY HELPERS
# ─────────────────────────────────────────

def _hash(value: str) -> str:
    """SHA-256 hash for anonymizing names and emails."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


# ─────────────────────────────────────────
# TEACHER FUNCTIONS
# ─────────────────────────────────────────

def insert_teacher(
    name: str,
    email: str,
    school_name: Optional[str] = None,
    school_locale: str = "unknown",
    title1_status: str = "unknown",
    country: str = "unknown",
    grade_band: str = "unknown",
    num_students_typical: Optional[int] = None,
    lab_used_most: Optional[str] = None,
) -> int:
    """
    Insert a new teacher record. Name and email are hashed immediately.
    Returns the teacher's database ID.
    If teacher already exists (by email hash), returns existing ID.
    """
    name_hash = _hash(name)
    email_hash = _hash(email)

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO teachers (
                name_hash, email_hash, school_name, school_locale,
                title1_status, country, grade_band,
                num_students_typical, lab_used_most
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name_hash, email_hash, school_name, school_locale,
             title1_status, country, grade_band,
             num_students_typical, lab_used_most)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Teacher already exists — return existing ID
        row = conn.execute(
            "SELECT id FROM teachers WHERE email_hash = ?", (email_hash,)
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


def get_teacher_by_email(email: str) -> Optional[dict]:
    """Retrieve teacher record by email (hashed internally)."""
    email_hash = _hash(email)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM teachers WHERE email_hash = ?", (email_hash,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_teacher_last_seen(teacher_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE teachers SET last_seen_at = ? WHERE id = ?",
        (datetime.now(), teacher_id)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# PROJECT FUNCTIONS
# ─────────────────────────────────────────

def insert_project(
    teacher_id: int,
    lab_id: int,
    track: str,
    project_description: Optional[str] = None,
    project_type_id: Optional[int] = None,
    num_students_involved: Optional[int] = None,
    project_duration_weeks: Optional[int] = None,
    carbon_lbs_estimated: Optional[float] = None,
    carbon_calculation_json: Optional[dict] = None,
    carbon_target_met: Optional[int] = None,
    community_score_total: Optional[float] = None,
    community_score_json: Optional[dict] = None,
    rubric_score_json: Optional[dict] = None,
    rubric_total: Optional[float] = None,
    people_reached: Optional[int] = None,
    sustained_action: Optional[int] = None,
    equity_flag: Optional[int] = None,
    funder_summary_text: Optional[str] = None,
    logic_model_json: Optional[dict] = None,
    submission_source: str = "in_app",
) -> int:
    """
    Insert a project record. JSON fields are serialized automatically.
    Returns the project's database ID.
    Follow-up date is automatically set to 3 months from today.
    """
    from dateutil.relativedelta import relativedelta
    followup_date = (date.today() + relativedelta(months=3)).isoformat()

    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects (
            teacher_id, lab_id, track, project_description, project_type_id,
            num_students_involved, project_duration_weeks,
            carbon_lbs_estimated, carbon_calculation_json, carbon_target_met,
            community_score_total, community_score_json,
            rubric_score_json, rubric_total,
            people_reached, sustained_action, equity_flag,
            funder_summary_text, logic_model_json,
            followup_date, submission_source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            teacher_id, lab_id, track, project_description, project_type_id,
            num_students_involved, project_duration_weeks,
            carbon_lbs_estimated,
            json.dumps(carbon_calculation_json) if carbon_calculation_json else None,
            carbon_target_met,
            community_score_total,
            json.dumps(community_score_json) if community_score_json else None,
            json.dumps(rubric_score_json) if rubric_score_json else None,
            rubric_total,
            people_reached, sustained_action, equity_flag,
            funder_summary_text,
            json.dumps(logic_model_json) if logic_model_json else None,
            followup_date, submission_source
        )
    )
    conn.commit()
    project_id = cursor.lastrowid
    conn.close()
    return project_id


def get_projects_due_followup() -> list[dict]:
    """Return all incomplete follow-ups that are due today or overdue."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.*, t.email_hash, l.lab_name
        FROM projects p
        JOIN teachers t ON p.teacher_id = t.id
        JOIN learning_labs l ON p.lab_id = l.id
        WHERE p.followup_completed = 0
          AND p.followup_date <= date('now')
        ORDER BY p.followup_date ASC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────
# SURVEY FUNCTIONS
# ─────────────────────────────────────────

def insert_survey(
    teacher_id: int,
    survey_type: str,                       # 'pre' or 'post'
    confidence_score: int,
    preparedness_score: int,
    implementation_frequency: str,
    student_engagement_score: Optional[int] = None,
    would_recommend: Optional[int] = None,
    open_feedback: Optional[str] = None,
    lab_id: Optional[int] = None,
) -> int:
    """Insert a pre or post survey response. Returns survey ID."""
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO pre_post_surveys (
            teacher_id, lab_id, survey_type,
            confidence_score, preparedness_score, implementation_frequency,
            student_engagement_score, would_recommend, open_feedback
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (teacher_id, lab_id, survey_type,
         confidence_score, preparedness_score, implementation_frequency,
         student_engagement_score, would_recommend, open_feedback)
    )
    conn.commit()
    survey_id = cursor.lastrowid
    conn.close()
    return survey_id


def get_survey_delta(teacher_id: int, lab_id: Optional[int] = None) -> Optional[dict]:
    """
    Calculate pre/post delta for a teacher.
    Returns dict with deltas, or None if pre or post is missing.
    """
    conn = get_connection()
    query = """
        SELECT survey_type,
               AVG(confidence_score) as avg_confidence,
               AVG(preparedness_score) as avg_preparedness
        FROM pre_post_surveys
        WHERE teacher_id = ?
        {}
        GROUP BY survey_type
    """.format("AND lab_id = ?" if lab_id else "")

    params = (teacher_id, lab_id) if lab_id else (teacher_id,)
    rows = {r["survey_type"]: dict(r) for r in conn.execute(query, params).fetchall()}
    conn.close()

    if "pre" not in rows or "post" not in rows:
        return None

    return {
        "confidence_delta": round(
            rows["post"]["avg_confidence"] - rows["pre"]["avg_confidence"], 2
        ),
        "preparedness_delta": round(
            rows["post"]["avg_preparedness"] - rows["pre"]["avg_preparedness"], 2
        ),
        "pre": rows["pre"],
        "post": rows["post"],
    }


# ─────────────────────────────────────────
# IMPACT SUMMARY (for funder dashboard)
# ─────────────────────────────────────────

def get_impact_summary(
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    filter_country: Optional[str] = None,
    filter_lab: Optional[str] = None,
    filter_locale: Optional[str] = None,
) -> dict:
    """
    Aggregate all key metrics for the funder dashboard.
    All filters are optional — None means include everything.
    Returns a dict matching the logic model structure.
    """
    conn = get_connection()

    # Build WHERE clauses dynamically
    conditions = []
    params = []

    if date_start:
        conditions.append("p.created_at >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("p.created_at <= ?")
        params.append(date_end)
    if filter_country:
        conditions.append("t.country = ?")
        params.append(filter_country)
    if filter_lab:
        conditions.append("l.lab_name = ?")
        params.append(filter_lab)
    if filter_locale:
        conditions.append("t.school_locale = ?")
        params.append(filter_locale)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    project_stats = conn.execute(f"""
        SELECT
            COUNT(DISTINCT p.teacher_id)    AS total_teachers,
            COUNT(DISTINCT t.school_name)   AS total_schools,
            SUM(p.num_students_involved)    AS total_students,
            COUNT(p.id)                     AS total_projects,
            COUNT(DISTINCT t.country)       AS countries_represented,
            ROUND(AVG(p.rubric_total), 2)   AS avg_rubric_score,
            ROUND(AVG(p.community_score_total), 2) AS avg_community_score,
            SUM(CASE WHEN p.track='A' THEN p.carbon_lbs_estimated ELSE 0 END) AS total_carbon_lbs,
            ROUND(100.0 * SUM(CASE WHEN t.title1_status='yes' THEN 1 ELSE 0 END)
                  / COUNT(p.id), 1) AS pct_title1_schools,
            ROUND(100.0 * SUM(CASE WHEN p.equity_flag=1 THEN 1 ELSE 0 END)
                  / COUNT(p.id), 1) AS pct_underserved_projects,
            ROUND(100.0 * SUM(CASE WHEN p.sustained_action=1 THEN 1 ELSE 0 END)
                  / COUNT(p.id), 1) AS pct_projects_sustained
        FROM projects p
        JOIN teachers t ON p.teacher_id = t.id
        JOIN learning_labs l ON p.lab_id = l.id
        {where}
    """, params).fetchone()

    # Survey deltas (aggregate across all teachers in filter)
    survey_stats = conn.execute(f"""
        SELECT
            survey_type,
            ROUND(AVG(confidence_score), 2)    AS avg_confidence,
            ROUND(AVG(preparedness_score), 2)  AS avg_preparedness
        FROM pre_post_surveys s
        JOIN teachers t ON s.teacher_id = t.id
        {"WHERE t.country = ?" if filter_country else ""}
        GROUP BY survey_type
    """, [filter_country] if filter_country else []).fetchall()

    survey_by_type = {r["survey_type"]: dict(r) for r in survey_stats}
    pre = survey_by_type.get("pre", {})
    post = survey_by_type.get("post", {})

    conn.close()

    stats = dict(project_stats)
    return {
        # OUTPUTS (what EPA calls outputs — scale metrics)
        "total_teachers": stats.get("total_teachers", 0),
        "total_schools": stats.get("total_schools", 0),
        "total_students": stats.get("total_students", 0),
        "total_projects": stats.get("total_projects", 0),
        "countries_represented": stats.get("countries_represented", 0),
        "pct_title1_schools": stats.get("pct_title1_schools", 0),
        "pct_underserved_projects": stats.get("pct_underserved_projects", 0),

        # SHORT-TERM OUTCOMES (teacher capacity delta)
        "avg_pre_confidence": pre.get("avg_confidence"),
        "avg_post_confidence": post.get("avg_confidence"),
        "confidence_delta": round(
            (post.get("avg_confidence") or 0) - (pre.get("avg_confidence") or 0), 2
        ) if pre and post else None,
        "avg_pre_preparedness": pre.get("avg_preparedness"),
        "avg_post_preparedness": post.get("avg_preparedness"),
        "preparedness_delta": round(
            (post.get("avg_preparedness") or 0) - (pre.get("avg_preparedness") or 0), 2
        ) if pre and post else None,

        # INTERMEDIATE OUTCOMES (impact metrics)
        "total_carbon_lbs": stats.get("total_carbon_lbs", 0),
        "avg_community_score": stats.get("avg_community_score"),
        "avg_rubric_score": stats.get("avg_rubric_score"),
        "pct_projects_sustained": stats.get("pct_projects_sustained", 0),
    }



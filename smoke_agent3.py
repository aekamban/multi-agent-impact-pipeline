"""
smoke_agent3.py
Manual end-to-end check for Agent 3.
"""

import json
import os
import sqlite3
import tempfile

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["TCIMPACT_DB_PATH"] = db_path

from database import initialize_db, get_connection
initialize_db()
print(f"DB initialized at: {db_path}")

from project_state import (
    ProjectState, RawInput, TeacherContext,
    SchoolLocale, SchoolType, Phase
)

state = ProjectState(
    raw_input=RawInput(
        raw_lab_name="agriculture lab",
        raw_project_description=(
            "Students measured compost rates over 6 weeks and "
            "presented findings to the cafeteria manager. The school "
            "now has a composting bin in the cafeteria as a result."
        ),
        raw_student_count_text="10-25, K-8th",
        raw_community_partners="Local food bank, cafeteria staff",
        raw_location="Norwalk, CT",
    ),
    teacher_context=TeacherContext(
        school_name="Jefferson Montessori",
        subject_area="Environmental Science",
        curriculum_standard="NGSS",
        city="Norwalk",
        state_province="CT",
        country="US",
        school_locale=SchoolLocale.URBAN,
        school_type=SchoolType.MONTESSORI,
        title1_status="yes",
    )
)

print("\n--- Raw input ---")
print(f"  lab name: '{state.raw_input.raw_lab_name}'")
print(f"  student count: '{state.raw_input.raw_student_count_text}'")

from agent2 import process_submission
state = process_submission(state.raw_input, state.teacher_context)
state.phase = Phase.IMPLEMENTING

si = state.structured_intake
print("\n--- Agent 2 output ---")
print(f"  canonical_lab_name:    {si.canonical_lab_name}")
print(f"  track:                 {si.track}")
print(f"  num_students_estimate: {si.num_students_estimate}")
print(f"  community_partners:    {[p.name for p in si.community_partnerships]}")
print(f"  sustained_action:      {si.sustained_action}")
print(f"  equity_flag:           {si.equity_flag}")
print(f"  project_type:          {si.project_type}")

from agent3 import run_agent3, write_impact_to_db_with_flags
conn = get_connection()
conn.execute("PRAGMA foreign_keys = OFF")
conn.commit()
conn.close()
state = run_agent3(state)

m = state.impact_metrics
print("\n--- Agent 3 output ---")
print(f"  impact_track:          {m.impact_track}")
print(f"  reach_estimate:        {m.reach_estimate}")
print(f"  behavior_change_proxy: {m.behavior_change_proxy}")
print(f"  awareness_scale:       {m.awareness_scale}")
print(f"  partnership_count:     {m.partnership_count}")
print(f"  community_score_total: {m.community_score_total}")
print(f"  community_score_json:  {m.community_score_json}")
print(f"  policy_influence_flag: {m.policy_influence_flag}")
print(f"  methodology_notes:     {m.methodology_notes[:120]}...")

conn = get_connection()
conn.execute("PRAGMA foreign_keys = OFF")

conn.execute(
    "INSERT OR IGNORE INTO learning_labs (lab_name, track, thematic_topic) VALUES (?,?,?)",
    (si.canonical_lab_name, si.track.value if si.track else "B", "Food & Land Use")
)
conn.commit()
lab_row = conn.execute(
    "SELECT id FROM learning_labs WHERE lab_name = ?", (si.canonical_lab_name,)
).fetchone()
lab_id = lab_row["id"]

conn.execute(
    "INSERT INTO sessions (teacher_id, lab_id, classroom_code, academic_year, status) VALUES (1,?,?,?,?)",
    (lab_id, "SMOKE01", "2024-2025", "implementing")
)
conn.commit()
session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

conn.execute(
    "INSERT INTO student_groups (session_id, group_name, num_students) VALUES (?,?,?)",
    (session_id, "Smoke Test Group", si.num_students_estimate or 18)
)
conn.commit()
group_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

conn.execute(
    "INSERT INTO projects (group_id, session_id, lab_id, track) VALUES (?,?,?,?)",
    (group_id, session_id, lab_id, si.track.value if si.track else "B")
)
conn.commit()
project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
conn.close()

print(f"\n--- Inserted project row (id={project_id}) ---")

write_impact_to_db_with_flags(
    project_id=project_id,
    metrics=m,
    sustained_action=si.sustained_action,
    equity_flag=si.equity_flag,
    db_path=db_path,
)
print("write_impact_to_db_with_flags() completed")

conn = get_connection()
row = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())
conn.close()

print("\n--- DB row after Agent 3 write ---")
for f in ["id","track","people_reached","community_score_total",
          "community_partnerships_count","sustained_action","equity_flag"]:
    print(f"  {f}: {row.get(f)}")

if row.get("community_score_json"):
    print(f"  community_score_json: {json.loads(row['community_score_json'])}")

if row.get("carbon_calculation_json"):
    ext = json.loads(row["carbon_calculation_json"]).get("extended_metrics", {})
    print(f"  extended_metrics.behavior_change_proxy: {ext.get('behavior_change_proxy')}")
    print(f"  extended_metrics.awareness_scale:       {ext.get('awareness_scale')}")
    print(f"  extended_metrics.methodology_notes:     {str(ext.get('methodology_notes',''))[:100]}...")

print("\nSmoke test complete.")

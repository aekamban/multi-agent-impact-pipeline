"""
TCImpact Database Tests
Tests the schema and all database functions with sample data.
Run with: python test_database.py
"""

import os
import json
import sqlite3

# Use a test database so we don't touch the real one
os.environ["TCIMPACT_DB_PATH"] = "tcimpact_test.db"

# Remove old test DB if it exists
if os.path.exists("tcimpact_test.db"):
    os.remove("tcimpact_test.db")

from database import (
    initialize_db, insert_teacher, get_teacher_by_email,
    insert_project, get_projects_due_followup,
    insert_survey, get_survey_delta,
    get_impact_summary
)

print("=" * 60)
print("TCImpact Database Tests")
print("=" * 60)

# ── SETUP ──────────────────────────────────────────────────────
print("\n1. Initializing database...")
initialize_db()
print("   ✓ Tables created")

# ── TEACHERS ───────────────────────────────────────────────────
print("\n2. Inserting test teachers...")

teacher_1_id = insert_teacher(
    name="Maria Santos",
    email="maria.santos@escola.br",
    school_name="Escola Clima Verde",
    school_locale="urban",
    title1_status="yes",
    country="Brazil",
    grade_band="high",
    num_students_typical=28,
    lab_used_most="Climate Impacts and Solutions with En-ROADS"
)

teacher_2_id = insert_teacher(
    name="James Okafor",
    email="j.okafor@school.ng",
    school_name="Lagos Community Secondary",
    school_locale="urban",
    title1_status="yes",
    country="Nigeria",
    grade_band="high",
    num_students_typical=35,
    lab_used_most="Renewable Energy"
)

teacher_3_id = insert_teacher(
    name="Sarah Chen",
    email="schen@highschool.us",
    school_name="Westfield High",
    school_locale="suburban",
    title1_status="no",
    country="United States",
    grade_band="high",
    num_students_typical=24,
    lab_used_most="Climate Justice and Equity"
)

print(f"   ✓ Teacher 1 ID: {teacher_1_id} (Brazil, Track A lab)")
print(f"   ✓ Teacher 2 ID: {teacher_2_id} (Nigeria, Track B lab)")
print(f"   ✓ Teacher 3 ID: {teacher_3_id} (US, Track B lab)")

# Test duplicate handling
teacher_1_duplicate = insert_teacher(
    name="Maria Santos",
    email="maria.santos@escola.br",
    school_name="Escola Clima Verde",
)
assert teacher_1_duplicate == teacher_1_id, "Duplicate teacher should return existing ID"
print("   ✓ Duplicate teacher handled correctly")

# Test get by email
fetched = get_teacher_by_email("maria.santos@escola.br")
assert fetched is not None
assert fetched["country"] == "Brazil"
print("   ✓ Teacher retrieval by email works")

# ── PROJECTS ───────────────────────────────────────────────────
print("\n3. Inserting test projects...")

# Get lab IDs from DB
conn = sqlite3.connect("tcimpact_test.db")
conn.row_factory = sqlite3.Row
enroads_lab = conn.execute(
    "SELECT id FROM learning_labs WHERE lab_name = 'Climate Impacts and Solutions with En-ROADS'"
).fetchone()
renewable_lab = conn.execute(
    "SELECT id FROM learning_labs WHERE lab_name = 'Renewable Energy'"
).fetchone()
justice_lab = conn.execute(
    "SELECT id FROM learning_labs WHERE lab_name = 'Climate Justice and Equity'"
).fetchone()
conn.close()

# Track A project — En-ROADS, quantitative carbon
project_1_id = insert_project(
    teacher_id=teacher_1_id,
    lab_id=enroads_lab["id"],
    track="A",
    project_description=(
        "Students designed an energy efficiency audit of our school building. "
        "We identified 12 classrooms with inefficient lighting and worked with "
        "the principal to switch to LED bulbs. We calculated our CO2 reduction "
        "using the EPA emissions calculator."
    ),
    num_students_involved=28,
    project_duration_weeks=10,
    carbon_lbs_estimated=11200.0,
    carbon_calculation_json={
        "method": "EPA emissions factor - electricity",
        "kwh_saved_per_year": 4200,
        "lbs_per_kwh": 0.92,
        "weeks": 10,
        "assumption": "Based on EPA eGRID 2022 Brazil average emissions factor"
    },
    carbon_target_met=1,
    community_score_total=14.0,
    community_score_json={
        "reach": 4, "depth": 3, "equity": 3, "sustainability": 4
    },
    rubric_score_json={
        "reach": 4, "depth": 4, "equity": 3, "sustainability": 4, "fidelity": 5
    },
    rubric_total=20.0,
    people_reached=450,
    sustained_action=1,
    equity_flag=1,
    funder_summary_text=(
        "28 students conducted an energy efficiency audit reducing school "
        "electricity consumption and achieving 11,200 lbs CO2 reduction, "
        "exceeding the 10,000 lb target."
    ),
)

# Track B project — Renewable Energy awareness campaign
project_2_id = insert_project(
    teacher_id=teacher_2_id,
    lab_id=renewable_lab["id"],
    track="B",
    project_description=(
        "Students created a social media campaign and community exhibition "
        "about solar energy adoption in Lagos. They interviewed 8 local "
        "business owners and presented findings to the city council."
    ),
    num_students_involved=35,
    project_duration_weeks=8,
    carbon_lbs_estimated=None,
    community_score_total=17.0,
    community_score_json={
        "reach": 5, "depth": 4, "equity": 4, "sustainability": 4
    },
    rubric_score_json={
        "reach": 5, "depth": 4, "equity": 4, "sustainability": 3, "fidelity": 4
    },
    rubric_total=20.0,
    people_reached=1200,
    sustained_action=1,
    equity_flag=1,
)

# Track B project — Climate Justice policy advocacy
project_3_id = insert_project(
    teacher_id=teacher_3_id,
    lab_id=justice_lab["id"],
    track="B",
    project_description=(
        "Students wrote letters to their state representatives about "
        "environmental justice in their community. They focused on a "
        "local industrial facility affecting a low-income neighborhood."
    ),
    num_students_involved=24,
    project_duration_weeks=6,
    community_score_total=16.0,
    community_score_json={
        "reach": 3, "depth": 5, "equity": 5, "sustainability": 3
    },
    rubric_score_json={
        "reach": 3, "depth": 5, "equity": 5, "sustainability": 3, "fidelity": 4
    },
    rubric_total=20.0,
    people_reached=85,
    sustained_action=0,
    equity_flag=1,
)

# Track B — low scoring project for contrast
project_4_id = insert_project(
    teacher_id=teacher_3_id,
    lab_id=renewable_lab["id"],
    track="B",
    project_description="Students made posters about renewable energy.",
    num_students_involved=22,
    project_duration_weeks=3,
    community_score_total=8.0,
    community_score_json={
        "reach": 2, "depth": 2, "equity": 2, "sustainability": 2
    },
    rubric_score_json={
        "reach": 2, "depth": 2, "equity": 2, "sustainability": 2, "fidelity": 3
    },
    rubric_total=11.0,
    people_reached=30,
    sustained_action=0,
    equity_flag=0,
)

# Track A — project that didn't meet target
project_5_id = insert_project(
    teacher_id=teacher_1_id,
    lab_id=enroads_lab["id"],
    track="A",
    project_description=(
        "Students designed a composting program for the school cafeteria "
        "to reduce food waste and methane emissions."
    ),
    num_students_involved=28,
    project_duration_weeks=10,
    carbon_lbs_estimated=4200.0,
    carbon_calculation_json={
        "method": "EPA emissions factor - food waste",
        "tons_food_diverted": 0.8,
        "lbs_co2e_per_ton": 5250,
        "assumption": "EPA WARM model default for food waste composting"
    },
    carbon_target_met=0,
    community_score_total=13.0,
    community_score_json={
        "reach": 3, "depth": 4, "equity": 3, "sustainability": 3
    },
    rubric_score_json={
        "reach": 3, "depth": 4, "equity": 3, "sustainability": 4, "fidelity": 4
    },
    rubric_total=18.0,
    people_reached=200,
    sustained_action=1,
    equity_flag=1,
)

print(f"   ✓ 5 projects inserted (IDs: {project_1_id}-{project_5_id})")
print(f"   ✓ Track A projects: 2, Track B projects: 3")

# ── SURVEYS ────────────────────────────────────────────────────
print("\n4. Inserting pre/post surveys...")

enroads_lab_id = enroads_lab["id"]

# Teacher 1 — strong improvement
insert_survey(teacher_1_id, "pre", confidence_score=2, preparedness_score=2,
              implementation_frequency="this is my first time", lab_id=enroads_lab_id)
insert_survey(teacher_1_id, "post", confidence_score=4, preparedness_score=4,
              implementation_frequency="this is my first time",
              student_engagement_score=5, would_recommend=5,
              open_feedback="The En-ROADS simulator was transformative for my students.",
              lab_id=enroads_lab_id)

# Teacher 2 — moderate improvement
insert_survey(teacher_2_id, "pre", confidence_score=3, preparedness_score=3,
              implementation_frequency="1-2 times before")
insert_survey(teacher_2_id, "post", confidence_score=4, preparedness_score=5,
              implementation_frequency="1-2 times before",
              student_engagement_score=4, would_recommend=5,
              open_feedback="Students loved the community exhibition component.")

# Teacher 3 — experienced teacher, smaller delta
insert_survey(teacher_3_id, "pre", confidence_score=4, preparedness_score=4,
              implementation_frequency="3-5 times before")
insert_survey(teacher_3_id, "post", confidence_score=5, preparedness_score=5,
              implementation_frequency="3-5 times before",
              student_engagement_score=4, would_recommend=4,
              open_feedback="The policy action component is very powerful.")

print("   ✓ 6 surveys inserted (3 pre, 3 post)")

# ── VERIFY DELTAS ──────────────────────────────────────────────
print("\n5. Verifying survey deltas...")

delta = get_survey_delta(teacher_1_id)
assert delta is not None
assert delta["confidence_delta"] == 2.0
assert delta["preparedness_delta"] == 2.0
print(f"   ✓ Teacher 1 confidence delta: +{delta['confidence_delta']}")
print(f"   ✓ Teacher 1 preparedness delta: +{delta['preparedness_delta']}")

# ── IMPACT SUMMARY ────────────────────────────────────────────
print("\n6. Generating aggregate impact summary...")

summary = get_impact_summary()
print(f"   ✓ Total teachers: {summary['total_teachers']}")
print(f"   ✓ Total projects: {summary['total_projects']}")
print(f"   ✓ Total students: {summary['total_students']}")
print(f"   ✓ Countries: {summary['countries_represented']}")
print(f"   ✓ Total carbon lbs (Track A): {summary['total_carbon_lbs']}")
print(f"   ✓ Avg community score: {summary['avg_community_score']}")
print(f"   ✓ Avg rubric score: {summary['avg_rubric_score']}")
print(f"   ✓ % Title I schools: {summary['pct_title1_schools']}%")
print(f"   ✓ % Underserved projects: {summary['pct_underserved_projects']}%")
print(f"   ✓ Confidence delta: {summary['confidence_delta']}")
print(f"   ✓ Preparedness delta: {summary['preparedness_delta']}")

# Test country filter
us_summary = get_impact_summary(filter_country="United States")
assert us_summary["total_teachers"] == 1
print(f"   ✓ Country filter works (US: {us_summary['total_projects']} projects)")

# ── FOLLOW-UP CHECK ───────────────────────────────────────────
print("\n7. Checking follow-up tracking...")
# Set one project's followup date to today to test
conn = sqlite3.connect("tcimpact_test.db")
conn.execute("UPDATE projects SET followup_date = date('now') WHERE id = ?",
             (project_2_id,))
conn.commit()
conn.close()

due = get_projects_due_followup()
assert len(due) >= 1
print(f"   ✓ {len(due)} project(s) due for follow-up")

# ── CLEANUP ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("All tests passed! ✓")
print("=" * 60)
print(f"\nTest database saved at: tcimpact_test.db")
print("You can inspect it with: sqlite3 tcimpact_test.db")


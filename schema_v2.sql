-- Multi-Agent Impact Pipeline: Database Schema v2
-- Longitudinal learning companion for program teachers and students
-- Supports three phases: Planning → Implementation → Analysis
-- Updated: Day 2 based on real intake-form data analysis and program staff input
-- 
-- KEY DESIGN DECISIONS:
-- 1. Sessions are the central unit (one teacher + one lab + one academic year)
-- 2. Planning data is mutable until implementation starts, then locks
-- 3. Student groups are anonymous — linked to sessions via classroom code only
-- 4. Upsert pattern used throughout planning phase to avoid duplicate records
-- 5. Map export JSON built into projects for the organization's public impact map

-- ─────────────────────────────────────────
-- LOOKUP TABLES
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS learning_labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Canonical name (what we use internally)
    lab_name TEXT NOT NULL UNIQUE,
    track TEXT NOT NULL CHECK(track IN ('A', 'B')),
    carbon_target_lbs REAL,
    thematic_topic TEXT,
    -- Example usage frequency (informs default suggestions)
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Canonical lab names + real-world alias mapping
INSERT OR IGNORE INTO learning_labs 
    (lab_name, track, carbon_target_lbs, thematic_topic, usage_count) 
VALUES
    ('Climate Impacts and Solutions with En-ROADS','A',10000,'Climate Solutions & Modeling',6),
    ('Agriculture and Climate Change','B',NULL,'Food & Land Use',10),
    ('Civics Climate Action','B',NULL,'Policy & Civic Action',8),
    ('Climate Justice and Equity','B',NULL,'Justice & Equity',7),
    ('Renewable Energy','B',NULL,'Energy',5),
    ('Wildfires','B',NULL,'Climate Impacts',3),
    ('Floods and Droughts','B',NULL,'Climate Impacts',2),
    ('Sea Level Rise','B',NULL,'Climate Impacts',2),
    ('Invasive Species','B',NULL,'Ecosystems',1),
    ('Climate Change and Health','B',NULL,'Health',1),
    ('Climate Migration','B',NULL,'Justice & Equity',0);

-- Lab name aliases from real Jotform submissions
-- Agent 2 uses this table for fuzzy matching
CREATE TABLE IF NOT EXISTS lab_name_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL UNIQUE,        -- as submitted by teacher
    canonical_lab_id INTEGER NOT NULL REFERENCES learning_labs(id),
    confidence REAL DEFAULT 1.0        -- 1.0 = exact, <1.0 = fuzzy match
);

INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Agriculture and Climate Change', id, 1.0 FROM learning_labs WHERE lab_name = 'Agriculture and Climate Change';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Climate Impacts and Solutions with En-ROADS', id, 1.0 FROM learning_labs WHERE lab_name = 'Climate Impacts and Solutions with En-ROADS';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Civics Climate Action', id, 1.0 FROM learning_labs WHERE lab_name = 'Civics Climate Action';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Climate Justice and Equity', id, 1.0 FROM learning_labs WHERE lab_name = 'Climate Justice and Equity';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Renewable Energy', id, 1.0 FROM learning_labs WHERE lab_name = 'Renewable Energy';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Sustainability and greening', id, 0.7 FROM learning_labs WHERE lab_name = 'Agriculture and Climate Change';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Invasive Species', id, 1.0 FROM learning_labs WHERE lab_name = 'Invasive Species';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Floods and Droughts', id, 1.0 FROM learning_labs WHERE lab_name = 'Floods and Droughts';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Sea Level Rise', id, 1.0 FROM learning_labs WHERE lab_name = 'Sea Level Rise';
INSERT OR IGNORE INTO lab_name_aliases (alias, canonical_lab_id, confidence)
SELECT 'Wildfires', id, 1.0 FROM learning_labs WHERE lab_name = 'Wildfires';

CREATE TABLE IF NOT EXISTS project_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name TEXT NOT NULL UNIQUE,
    track_relevance TEXT NOT NULL CHECK(track_relevance IN ('A','B','both')),
    carbon_quantifiable INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO project_types (type_name, track_relevance, carbon_quantifiable) VALUES
    ('Energy reduction/efficiency','A',1),
    ('Renewable energy installation','A',1),
    ('Tree planting / reforestation','both',1),
    ('Composting program','both',1),
    ('Food waste reduction','both',1),
    ('Transportation behavior change','both',1),
    ('Recycling program','both',1),
    ('School/community garden','both',0),
    ('Awareness / communications campaign','B',0),
    ('Policy advocacy / letter writing','B',0),
    ('Habitat restoration / invasive species removal','B',0),
    ('Environmental trail / outdoor classroom','B',0),
    ('Nature journaling / citizen science','B',0),
    ('Youth engagement / club','B',0),
    ('Curriculum integration / life cycle analysis','B',0),
    ('Other','both',0);

-- ─────────────────────────────────────────
-- TEACHERS
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name_hash TEXT NOT NULL UNIQUE,
    email_hash TEXT NOT NULL UNIQUE,
    school_name TEXT,
    -- Demographics the org wants but doesn't currently collect systematically
    school_type TEXT CHECK(school_type IN (
        'public','private','charter','montessori',
        'community_org','tribal_school','international','other','unknown'
    )) DEFAULT 'unknown',
    school_locale TEXT CHECK(school_locale IN (
        'urban','suburban','rural','unknown'
    )) DEFAULT 'unknown',
    title1_status TEXT CHECK(title1_status IN (
        'yes','no','unknown'
    )) DEFAULT 'unknown',
    -- Location (split for map integration)
    city TEXT,
    state_province TEXT,
    country TEXT DEFAULT 'unknown',
    -- Teaching context
    grade_band TEXT CHECK(grade_band IN (
        'elementary','middle','high','mixed','unknown'
    )) DEFAULT 'unknown',
    subject_area TEXT,              -- e.g. "Environmental Science, Biology"
    num_students_typical INTEGER,
    -- Program relationship
    program_educator_id TEXT,       -- if the org provides one in future
    years_in_program INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SESSIONS  (core unit: one teacher + one lab + one academic year)
-- This is the mutable planning record that locks when implementation begins
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    lab_id INTEGER REFERENCES learning_labs(id),
    classroom_code TEXT UNIQUE NOT NULL,  -- e.g. "PGM-7X4K"
    academic_year TEXT,                   -- e.g. "2024-25"

    -- Phase tracking (planning data is mutable until 'implementing')
    status TEXT NOT NULL CHECK(status IN (
        'planning','implementing','analyzing','complete'
    )) DEFAULT 'planning',

    -- Planning phase fields (mutable, overwritten as teacher refines)
    planned_num_groups INTEGER DEFAULT 1,
    planned_start_date DATE,
    planned_end_date DATE,
    planned_duration_weeks INTEGER,
    curriculum_alignment TEXT,      -- how teacher connects lab to their course
    local_context TEXT,             -- local environmental issues informing choice
    available_resources TEXT,       -- field trips, tech, community partners etc.
    teacher_notes TEXT,

    -- Implementation tracking
    implementation_started_at TIMESTAMP,
    implementation_notes TEXT,

    -- Analysis / completion
    completed_at TIMESTAMP,
    jotform_draft_text TEXT,        -- AI-drafted Jotform submission
    jotform_submitted INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- STUDENT GROUPS (anonymous, linked to sessions)
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS student_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    group_name TEXT,                -- e.g. "Group A" or student-chosen name
    num_students INTEGER,
    -- Ability/context flags (set by teacher, informs agent suggestions)
    ability_level TEXT CHECK(ability_level IN (
        'mixed','advanced','grade_level','support_needed','unknown'
    )) DEFAULT 'unknown',
    has_field_trip_access INTEGER DEFAULT 0,
    has_device_access INTEGER DEFAULT 1,
    special_interests TEXT,         -- e.g. "interested in marine biology"

    -- Phase tracking (mirrors session but at group level)
    status TEXT NOT NULL CHECK(status IN (
        'planning','implementing','analyzing','complete'
    )) DEFAULT 'planning',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- PROJECTS (one per student group)
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES student_groups(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    lab_id INTEGER NOT NULL REFERENCES learning_labs(id),
    project_type_id INTEGER REFERENCES project_types(id),
    track TEXT NOT NULL CHECK(track IN ('A','B')),

    -- Core description
    project_title TEXT,
    project_description TEXT,
    thematic_topic TEXT,

    -- Student count (normalized from messy input like "10-25, K-8th")
    num_students_min INTEGER,
    num_students_max INTEGER,
    num_students_display TEXT,      -- original messy value preserved

    -- Duration
    duration_weeks INTEGER,
    start_date DATE,
    end_date DATE,

    -- Carbon impact (Track A primarily)
    carbon_lbs_estimated REAL,
    carbon_calculation_json TEXT,   -- methodology + assumptions as JSON
    carbon_target_met INTEGER,      -- 1=yes, 0=no, NULL=not applicable

    -- Community impact
    community_score_total REAL,
    community_score_json TEXT,      -- {reach, depth, equity, sustainability}
    people_reached INTEGER,
    people_reached_display TEXT,    -- e.g. "500+" preserved as submitted

    -- Community partnerships (extracted from narrative by Agent 2)
    community_partnerships_json TEXT,   -- [{name, type, description}]
    community_partnerships_count INTEGER DEFAULT 0,

    -- Rubric scores (5 dimensions, 1-5 each)
    rubric_score_json TEXT,         -- {reach, depth, equity, sustainability, fidelity}
    rubric_total REAL,              -- 5-25

    -- Funder-facing flags
    sustained_action INTEGER,       -- 1=continues beyond class
    equity_flag INTEGER,            -- 1=serves underserved community

    -- Supporting evidence
    student_quotes TEXT,
    highlights TEXT,
    media_urls TEXT,                -- newline-separated URLs from Jotform

    -- Phase tracking
    status TEXT NOT NULL CHECK(status IN (
        'planning','implementing','analyzing','complete'
    )) DEFAULT 'planning',

    -- Agent outputs
    funder_summary_text TEXT,
    logic_model_json TEXT,

    -- Partner map export
    map_export_json TEXT,           -- {lat, lng, project_type, lab, grade_band, ...}

    -- Follow-up
    followup_date DATE,
    followup_completed INTEGER DEFAULT 0,
    followup_notes TEXT,

    -- Source
    submission_source TEXT CHECK(submission_source IN (
        'in_app','jotform_import','manual'
    )) DEFAULT 'in_app',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- PRE/POST TEACHER SURVEYS
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pre_post_surveys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    session_id INTEGER REFERENCES sessions(id),
    lab_id INTEGER REFERENCES learning_labs(id),
    survey_type TEXT NOT NULL CHECK(survey_type IN ('pre','post')),

    -- Core outcome metrics
    confidence_score INTEGER CHECK(confidence_score BETWEEN 1 AND 5),
    preparedness_score INTEGER CHECK(preparedness_score BETWEEN 1 AND 5),
    implementation_frequency TEXT CHECK(implementation_frequency IN (
        'this is my first time','1-2 times before',
        '3-5 times before','6+ times'
    )),
    -- Post-only fields
    student_engagement_score INTEGER CHECK(student_engagement_score BETWEEN 1 AND 5),
    would_recommend INTEGER CHECK(would_recommend BETWEEN 1 AND 5),

    -- Planning context (pre-survey only — informs agent suggestions)
    student_ability_context TEXT,
    available_resources_text TEXT,
    local_issue_context TEXT,

    open_feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- IMPACT SUMMARIES (funder dashboard + map export)
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS impact_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_range_start DATE,
    date_range_end DATE,
    filter_country TEXT,
    filter_lab TEXT,
    filter_locale TEXT,
    filter_school_type TEXT,

    -- Output metrics (EPA logic model: outputs)
    total_teachers INTEGER,
    total_students INTEGER,
    total_projects INTEGER,
    total_schools INTEGER,
    countries_represented INTEGER,
    pct_title1_schools REAL,
    pct_underserved_projects REAL,
    total_community_partnerships INTEGER,

    -- Outcome metrics (short-term)
    avg_pre_confidence REAL,
    avg_post_confidence REAL,
    confidence_delta REAL,
    avg_pre_preparedness REAL,
    avg_post_preparedness REAL,
    preparedness_delta REAL,

    -- Outcome metrics (intermediate)
    total_carbon_lbs REAL,
    avg_community_score REAL,
    avg_rubric_score REAL,
    pct_projects_sustained REAL,

    -- Generated artifacts
    summary_json TEXT,
    logic_model_text TEXT,
    map_export_json TEXT,           -- all projects in partner map format
    generated_by TEXT DEFAULT 'agent-4'
);

-- ─────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_sessions_teacher ON sessions(teacher_id);
CREATE INDEX IF NOT EXISTS idx_sessions_lab ON sessions(lab_id);
CREATE INDEX IF NOT EXISTS idx_sessions_code ON sessions(classroom_code);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_groups_session ON student_groups(session_id);
CREATE INDEX IF NOT EXISTS idx_projects_group ON projects(group_id);
CREATE INDEX IF NOT EXISTS idx_projects_session ON projects(session_id);
CREATE INDEX IF NOT EXISTS idx_projects_lab ON projects(lab_id);
CREATE INDEX IF NOT EXISTS idx_projects_track ON projects(track);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_followup ON projects(followup_date, followup_completed);
CREATE INDEX IF NOT EXISTS idx_teachers_country ON teachers(country);
CREATE INDEX IF NOT EXISTS idx_teachers_locale ON teachers(school_locale);
CREATE INDEX IF NOT EXISTS idx_teachers_type ON teachers(school_type);
CREATE INDEX IF NOT EXISTS idx_surveys_teacher ON pre_post_surveys(teacher_id);
CREATE INDEX IF NOT EXISTS idx_surveys_session ON pre_post_surveys(session_id);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON lab_name_aliases(alias);


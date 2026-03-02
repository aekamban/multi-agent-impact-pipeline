-- TCImpact POC Database Schema
-- All student data is anonymized. Teacher names are hashed.
-- Created: 2025-02-27

-- ─────────────────────────────────────────
-- LOOKUP TABLES
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS learning_labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_name TEXT NOT NULL UNIQUE,
    track TEXT NOT NULL CHECK(track IN ('A', 'B')),
    -- Track A = En-ROADS (quantitative carbon target)
    -- Track B = all other labs (awareness/community/policy)
    carbon_target_lbs REAL,         -- 10000 for Track A, NULL for Track B
    thematic_topic TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pre-populate learning labs
INSERT OR IGNORE INTO learning_labs (lab_name, track, carbon_target_lbs, thematic_topic) VALUES
    ('Climate Impacts and Solutions with En-ROADS', 'A', 10000, 'Climate Solutions & Modeling'),
    ('Renewable Energy', 'B', NULL, 'Energy'),
    ('Agriculture', 'B', NULL, 'Food & Land Use'),
    ('Sea Level Rise', 'B', NULL, 'Climate Impacts'),
    ('Wildfires', 'B', NULL, 'Climate Impacts'),
    ('Floods & Droughts', 'B', NULL, 'Climate Impacts'),
    ('Invasive Species', 'B', NULL, 'Ecosystems'),
    ('Civics & Climate Action', 'B', NULL, 'Policy & Civic Action'),
    ('Climate Justice and Equity', 'B', NULL, 'Justice & Equity'),
    ('Climate Migration', 'B', NULL, 'Justice & Equity'),
    ('Climate Change and Health', 'B', NULL, 'Health');

CREATE TABLE IF NOT EXISTS project_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name TEXT NOT NULL UNIQUE,
    track_relevance TEXT NOT NULL CHECK(track_relevance IN ('A', 'B', 'both')),
    carbon_quantifiable INTEGER NOT NULL DEFAULT 0  -- 1 = yes, 0 = no
);

INSERT OR IGNORE INTO project_types (type_name, track_relevance, carbon_quantifiable) VALUES
    ('Energy reduction/efficiency', 'A', 1),
    ('Renewable energy installation', 'A', 1),
    ('Tree planting / reforestation', 'both', 1),
    ('Composting program', 'both', 1),
    ('Food waste reduction', 'both', 1),
    ('Transportation behavior change', 'both', 1),
    ('Recycling program', 'both', 1),
    ('School garden', 'both', 0),
    ('Community garden', 'B', 0),
    ('Awareness / communications campaign', 'B', 0),
    ('Policy advocacy / letter writing', 'B', 0),
    ('Habitat restoration', 'B', 0),
    ('Invasive species removal', 'B', 0),
    ('Youth engagement project', 'B', 0),
    ('Other', 'both', 0);

-- ─────────────────────────────────────────
-- CORE TABLES
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Name is hashed for privacy; email hash used as stable identifier
    name_hash TEXT NOT NULL UNIQUE,
    email_hash TEXT NOT NULL UNIQUE,
    school_name TEXT,               -- not hashed — used for deduplication
    school_locale TEXT CHECK(school_locale IN ('urban', 'suburban', 'rural', 'unknown')),
    title1_status TEXT CHECK(title1_status IN ('yes', 'no', 'unknown')),
    country TEXT NOT NULL DEFAULT 'unknown',
    grade_band TEXT CHECK(grade_band IN (
        'elementary', 'middle', 'high', 'mixed', 'unknown'
    )),
    num_students_typical INTEGER,   -- typical class/cohort size
    lab_used_most TEXT REFERENCES learning_labs(lab_name),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    lab_id INTEGER NOT NULL REFERENCES learning_labs(id),
    project_type_id INTEGER REFERENCES project_types(id),
    track TEXT NOT NULL CHECK(track IN ('A', 'B')),

    -- Project description (free text — from Jotform or in-app input)
    project_description TEXT,
    num_students_involved INTEGER,
    project_duration_weeks INTEGER,

    -- Carbon impact (Track A primarily, optional for Track B)
    carbon_lbs_estimated REAL,
    carbon_calculation_json TEXT,   -- stores methodology + assumptions as JSON
    carbon_target_met INTEGER,      -- 1 = yes, 0 = no, NULL = not applicable

    -- Community impact score (Agent 4 output)
    community_score_total REAL,     -- 0-20 (sum of 4 dimensions x 5)
    community_score_json TEXT,      -- breakdown by dimension as JSON

    -- Rubric scores (Agent 2 output) — 5 dimensions, each 1-5
    rubric_score_json TEXT,         -- {reach, depth, equity, sustainability, fidelity}
    rubric_total REAL,              -- sum 5-25

    -- Funder-facing fields
    people_reached INTEGER,         -- estimated community members reached
    sustained_action INTEGER,       -- 1 = project continues beyond class, 0 = no
    equity_flag INTEGER,            -- 1 = serves underserved community

    -- Follow-up tracking
    followup_date DATE,             -- 3 months after submission
    followup_completed INTEGER DEFAULT 0,
    followup_notes TEXT,

    -- Agent-generated funder summary
    funder_summary_text TEXT,
    logic_model_json TEXT,

    -- Source tracking
    submission_source TEXT CHECK(submission_source IN (
        'in_app', 'jotform_import', 'manual'
    )) DEFAULT 'in_app',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pre_post_surveys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    lab_id INTEGER REFERENCES learning_labs(id),
    survey_type TEXT NOT NULL CHECK(survey_type IN ('pre', 'post')),

    -- Core outcome metrics funders care about
    confidence_score INTEGER CHECK(confidence_score BETWEEN 1 AND 5),
    -- "How confident are you teaching climate content?"
    preparedness_score INTEGER CHECK(preparedness_score BETWEEN 1 AND 5),
    -- "How prepared do you feel to facilitate this learning lab?"
    implementation_frequency TEXT CHECK(implementation_frequency IN (
        'this is my first time',
        '1-2 times before',
        '3-5 times before',
        '6+ times'
    )),
    student_engagement_score INTEGER CHECK(student_engagement_score BETWEEN 1 AND 5),
    -- "How engaged were your students?" (post only)
    would_recommend INTEGER CHECK(would_recommend BETWEEN 1 AND 5),
    -- Net promoter proxy (post only)
    open_feedback TEXT,             -- optional free text

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS impact_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_range_start DATE,
    date_range_end DATE,
    filter_country TEXT,            -- NULL = all countries
    filter_lab TEXT,                -- NULL = all labs
    filter_locale TEXT,             -- NULL = all locales

    -- Aggregate output metrics
    total_teachers INTEGER,
    total_students INTEGER,
    total_projects INTEGER,
    total_schools INTEGER,
    countries_represented INTEGER,
    pct_title1_schools REAL,
    pct_underserved_projects REAL,

    -- Aggregate outcome metrics
    avg_pre_confidence REAL,
    avg_post_confidence REAL,
    confidence_delta REAL,          -- post - pre
    avg_pre_preparedness REAL,
    avg_post_preparedness REAL,
    preparedness_delta REAL,

    -- Impact metrics
    total_carbon_lbs REAL,          -- Track A only
    avg_community_score REAL,
    avg_rubric_score REAL,
    pct_projects_sustained REAL,

    -- Generated artifacts
    summary_json TEXT,              -- full breakdown for dashboard
    logic_model_text TEXT,          -- grant-ready narrative
    generated_by TEXT DEFAULT 'agent-4'
);

-- ─────────────────────────────────────────
-- INDEXES (for common dashboard queries)
-- ─────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_projects_teacher ON projects(teacher_id);
CREATE INDEX IF NOT EXISTS idx_projects_lab ON projects(lab_id);
CREATE INDEX IF NOT EXISTS idx_projects_track ON projects(track);
CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at);
CREATE INDEX IF NOT EXISTS idx_projects_followup ON projects(followup_date, followup_completed);
CREATE INDEX IF NOT EXISTS idx_teachers_country ON teachers(country);
CREATE INDEX IF NOT EXISTS idx_teachers_locale ON teachers(school_locale);
CREATE INDEX IF NOT EXISTS idx_teachers_title1 ON teachers(title1_status);
CREATE INDEX IF NOT EXISTS idx_surveys_teacher ON pre_post_surveys(teacher_id);
CREATE INDEX IF NOT EXISTS idx_surveys_type ON pre_post_surveys(survey_type);


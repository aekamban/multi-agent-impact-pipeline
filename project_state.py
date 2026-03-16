"""
project_state.py
TCImpact — Shared Agent Handoff Object

ProjectState is the canonical object passed between agents.
Each agent writes only to its own section and never mutates others.

Section ownership:
    Agent 2 → structured_intake
    Agent 3 → impact_metrics
    Agent 4 → reporting

Usage pattern:
    state = ProjectState(raw_input=RawInput(...))
    state = agent2.process(state)    # populates structured_intake
    state = agent3.calculate(state)  # populates impact_metrics
    state = agent4.summarize(state)  # populates reporting

DB serialization is intentionally NOT in this file.
See project_state_adapter.py for all database read/write logic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────

class Phase(str, Enum):
    PLANNING = "planning"
    IMPLEMENTING = "implementing"
    ANALYZING = "analyzing"
    COMPLETE = "complete"


class Track(str, Enum):
    A = "A"   # En-ROADS / carbon calculation
    B = "B"   # Community impact labs


class SchoolLocale(str, Enum):
    URBAN = "urban"
    SUBURBAN = "suburban"
    RURAL = "rural"
    UNKNOWN = "unknown"


class SchoolType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    CHARTER = "charter"
    MONTESSORI = "montessori"
    TRIBAL = "tribal_school"
    COMMUNITY_ORG = "community_org"
    UNKNOWN = "unknown"


class GradeBand(str, Enum):
    ELEMENTARY = "elementary"   # K-5
    MIDDLE = "middle"           # 6-8
    HIGH = "high"               # 9-12
    MIXED = "mixed"             # spans multiple bands
    UNKNOWN = "unknown"


# ─────────────────────────────────────────
# NESTED MODELS
# ─────────────────────────────────────────

class RawInput(BaseModel):
    """
    Unprocessed teacher submission — preserved exactly as entered.
    Agent 2 reads this. No other agent should need to touch it.
    """
    raw_lab_name: str = ""
    raw_project_description: str = ""
    raw_student_count_text: str = ""       # e.g. "10-25, K-8th" or "500+"
    raw_additional_notes: str = ""
    raw_community_partners: str = ""       # narrative before structured extraction
    raw_location: str = ""                 # e.g. "Norwalk, CT" before parsing
    submission_source: str = "in_app"      # in_app | jotform_import | manual


class TeacherContext(BaseModel):
    """
    Teacher-level context captured at intake.
    Kept flat and lightweight — just what agents need at runtime.
    Full teacher record (hashed name/email) lives in the teachers SQLite table.
    """
    teacher_id: Optional[int] = None       # FK → teachers.id (set after DB write)
    school_name: str = ""
    subject_area: str = ""                 # e.g. "Chemistry", "Social Studies"
    curriculum_standard: str = "NGSS"     # NGSS | IB_MYP | UK_GCSE | Other
    city: str = ""
    state_province: str = ""
    country: str = ""                      # empty — do not default to "US"
    school_locale: SchoolLocale = SchoolLocale.UNKNOWN
    school_type: SchoolType = SchoolType.UNKNOWN
    title1_status: str = "unknown"         # yes | no | unknown


class CommunityPartner(BaseModel):
    name: str
    partner_type: str = ""                 # NGO, business, government, university, etc.
    description: str = ""


class RubricScores(BaseModel):
    """
    5-dimension rubric, 1–5 each.
    Partial scoring is valid for POC — teachers often submit incomplete data.
    Use scored_total for whatever is present; check is_complete before reporting.
    """
    reach: Optional[float] = None          # scale of people impacted
    depth: Optional[float] = None          # depth of engagement / behavior change
    equity: Optional[float] = None         # serves underserved communities
    sustainability: Optional[float] = None # action continues beyond class
    fidelity: Optional[float] = None       # alignment to TCI lab framework

    @property
    def dimensions(self) -> list[Optional[float]]:
        return [self.reach, self.depth, self.equity, self.sustainability, self.fidelity]

    @property
    def scored_dimensions_count(self) -> int:
        """How many of the 5 dimensions have been scored."""
        return sum(1 for d in self.dimensions if d is not None)

    @property
    def is_complete(self) -> bool:
        """True only when all 5 dimensions are present."""
        return self.scored_dimensions_count == 5

    @property
    def partial_total(self) -> Optional[float]:
        """Sum of whichever dimensions are present. None if none are scored yet.
        Use this for in-progress display — always label it as partial in UI."""
        valid = [d for d in self.dimensions if d is not None]
        return round(sum(valid), 2) if valid else None

    @property
    def complete_total(self) -> Optional[float]:
        """Sum of all 5 dimensions. None unless all 5 are present.
        Use this for funder reporting where a full score is required."""
        return round(sum(self.dimensions), 2) if self.is_complete else None  # type: ignore[arg-type]


class StructuredIntake(BaseModel):
    """
    Agent 2 output. Normalized, validated, matched.
    Agent 2 writes this section. Agent 3 and 4 read it but never write to it.
    """
    # Lab matching
    canonical_lab_name: str = ""
    canonical_lab_id: Optional[int] = None    # FK → learning_labs.id
    lab_match_confidence: float = 0.0         # 0.0–1.0; <0.8 triggers warning
    track: Optional[Track] = None

    # Student count (normalized from raw_student_count_text)
    num_students_min: Optional[int] = None
    num_students_max: Optional[int] = None
    num_students_estimate: Optional[int] = None   # midpoint for calculations
    num_students_display: str = ""                # original value preserved for Jotform

    # Project context
    thematic_topic: str = ""               # e.g. "Food & Land Use"
    project_duration_weeks: Optional[int] = None
    project_type: str = ""                 # e.g. "awareness campaign", "school garden"

    # Location / disaggregation (teacher-level fields mirrored here for agent convenience)
    # Full teacher record lives in TeacherContext and the teachers table
    grade_band: GradeBand = GradeBand.UNKNOWN

    # Community partnerships (extracted from raw narrative by Agent 2)
    community_partnerships: list[CommunityPartner] = Field(default_factory=list)

    # Rubric
    rubric_scores: RubricScores = Field(default_factory=RubricScores)

    # Funder flags
    sustained_action: Optional[bool] = None   # continues beyond class
    equity_flag: Optional[bool] = None        # serves underserved community


class LogicModel(BaseModel):
    """
    EPA logic model structure — both human-readable text and structured JSON.
    Agent 4 populates both.
    """
    inputs: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    short_term_outcomes: list[str] = Field(default_factory=list)
    intermediate_outcomes: list[str] = Field(default_factory=list)
    equity_note: str = ""

    def to_text(self) -> str:
        """Render logic model as a readable string for Jotform draft / funder summary."""
        sections = [
            ("INPUTS", self.inputs),
            ("ACTIVITIES", self.activities),
            ("OUTPUTS", self.outputs),
            ("SHORT-TERM OUTCOMES", self.short_term_outcomes),
            ("INTERMEDIATE OUTCOMES", self.intermediate_outcomes),
        ]
        lines = []
        for label, items in sections:
            if items:
                lines.append(f"{label}: {' → '.join(items)}")
        if self.equity_note:
            lines.append(f"EQUITY NOTE: {self.equity_note}")
        return "\n".join(lines)


class ImpactMetrics(BaseModel):
    """
    Agent 3 output. All fields start as None.
    Agent 3 writes this section. Agent 4 reads it but never writes to it.
    """
    impact_track: Optional[Track] = None

    # Track A — En-ROADS carbon
    co2_reduction_lbs: Optional[float] = None
    co2_reduction_methodology: str = ""    # step-by-step shown to students
    co2_target_met: Optional[bool] = None  # vs 10,000 lb TCI target
    epa_emissions_factor_used: str = ""    # e.g. "0.386 kg CO2/kWh (EPA 2023)"

    # Track B — Community impact
    reach_estimate: Optional[int] = None
    behavior_change_proxy: str = ""        # e.g. "composting pledges signed"
    awareness_scale: Optional[str] = None  # classroom | school | community | regional
    partnership_count: int = 0
    policy_influence_flag: bool = False
    policy_description: str = ""

    # Community scoring (used by Agent 4 for funder dashboard)
    community_score_total: Optional[float] = None
    community_score_json: Optional[dict[str, Any]] = None  # {reach, depth, equity, sustainability}

    # Shared
    methodology_notes: str = ""            # always surfaced — explainability is non-negotiable


class Reporting(BaseModel):
    """
    Agent 4 output. All fields start empty.
    Agent 4 writes this section. No other agent writes here.
    """
    logic_model: LogicModel = Field(default_factory=LogicModel)
    logic_model_text: str = ""             # human-readable rendering (from logic_model.to_text())
    jotform_draft: dict[str, str] = Field(default_factory=dict)  # keyed by Jotform column name
    funder_summary: str = ""               # grant-ready narrative paragraph
    map_export_json: dict[str, Any] = Field(default_factory=dict)  # Moore Foundation format


class DbIds(BaseModel):
    """
    SQLite foreign keys for cross-referencing ProjectState with database records.
    All None until database writes have occurred.
    """
    session_id: Optional[int] = None
    teacher_id: Optional[int] = None
    project_id: Optional[int] = None
    group_id: Optional[int] = None
    lab_id: Optional[int] = None


class Timestamps(BaseModel):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    intake_completed_at: Optional[datetime] = None
    impact_calculated_at: Optional[datetime] = None
    reporting_completed_at: Optional[datetime] = None

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


# ─────────────────────────────────────────
# ROOT MODEL
# ─────────────────────────────────────────

class ProjectState(BaseModel):
    """
    Canonical handoff object between TCImpact agents.
    One ProjectState per teacher project submission.
    Records remain mutable throughout all phases — projects pivot, that's expected.

    Agent 2 writes → structured_intake
    Agent 3 writes → impact_metrics
    Agent 4 writes → reporting
    """
    project_state_id: str = Field(default_factory=lambda: str(uuid4()))
    phase: Phase = Phase.PLANNING

    # Raw submission — preserved, never mutated after intake
    raw_input: RawInput = Field(default_factory=RawInput)

    # Teacher context (populated by Agent 2 from pre-survey / session)
    teacher_context: TeacherContext = Field(default_factory=TeacherContext)

    # Agent section outputs
    structured_intake: StructuredIntake = Field(default_factory=StructuredIntake)
    impact_metrics: ImpactMetrics = Field(default_factory=ImpactMetrics)
    reporting: Reporting = Field(default_factory=Reporting)

    # Cross-cutting
    db_ids: DbIds = Field(default_factory=DbIds)
    warnings: list[str] = Field(default_factory=list)
    low_confidence_fields: list[str] = Field(default_factory=list)
    timestamps: Timestamps = Field(default_factory=Timestamps)

    # ── Section update helpers ────────────────────────────────────────
    # Each agent calls its own helper and passes only the fields it's changing.
    # model_copy(update=...) is Pydantic v2's safe partial-update pattern.

    def update_structured_intake(self, **kwargs) -> "ProjectState":
        """Agent 2 uses this to update structured_intake fields without replacing the whole object."""
        updated_intake = self.structured_intake.model_copy(update=kwargs)
        self.structured_intake = updated_intake
        self.timestamps.touch()
        return self

    def update_impact_metrics(self, **kwargs) -> "ProjectState":
        """Agent 3 uses this to update impact_metrics fields."""
        updated_metrics = self.impact_metrics.model_copy(update=kwargs)
        self.impact_metrics = updated_metrics
        self.timestamps.touch()
        return self

    def update_reporting(self, **kwargs) -> "ProjectState":
        """Agent 4 uses this to update reporting fields."""
        updated_reporting = self.reporting.model_copy(update=kwargs)
        self.reporting = updated_reporting
        self.timestamps.touch()
        return self

    # ── Status helpers ────────────────────────────────────────────────

    def add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
        self.timestamps.touch()

    def flag_low_confidence(self, field_name: str) -> None:
        if field_name not in self.low_confidence_fields:
            self.low_confidence_fields.append(field_name)

    def is_intake_complete(self) -> bool:
        si = self.structured_intake
        return bool(
            si.canonical_lab_name
            and si.track is not None
            and si.num_students_estimate is not None
        )

    def is_ready_for_impact(self) -> bool:
        return self.is_intake_complete() and self.phase in (
            Phase.IMPLEMENTING, Phase.ANALYZING, Phase.COMPLETE
        )


# ─────────────────────────────────────────
# USAGE EXAMPLES (illustrative — not production code)
# ─────────────────────────────────────────

def _agent2_example() -> ProjectState:
    """Shows how Agent 2's process_submission() should build ProjectState."""

    # 1. Start from raw teacher submission
    state = ProjectState(
        raw_input=RawInput(
            raw_lab_name="agriculture lab",
            raw_project_description="Students measured compost rates and presented to the cafeteria manager.",
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

    # 2. Agent 2 populates structured_intake
    state.structured_intake = StructuredIntake(
        canonical_lab_name="Agriculture and Climate Change",
        canonical_lab_id=2,                # FK → learning_labs.id
        lab_match_confidence=0.92,
        track=Track.B,
        num_students_min=10,
        num_students_max=25,
        num_students_estimate=18,
        num_students_display="10-25, K-8th",
        thematic_topic="Food & Land Use",
        project_duration_weeks=6,
        project_type="awareness campaign",
        grade_band=GradeBand.ELEMENTARY,
        community_partnerships=[
            CommunityPartner(name="Local Food Bank", partner_type="NGO"),
            CommunityPartner(name="Cafeteria Staff", partner_type="school"),
        ],
        rubric_scores=RubricScores(
            reach=3.0, depth=4.0, equity=3.5, sustainability=4.0, fidelity=4.0
        ),
        sustained_action=True,
        equity_flag=True,
    )

    # 3. Warnings if match confidence is low
    if state.structured_intake.lab_match_confidence < 0.8:
        state.add_warning("Low confidence lab match — confirm lab name with teacher.")
        state.flag_low_confidence("canonical_lab_name")

    # 4. Advance phase, record timestamp
    state.phase = Phase.IMPLEMENTING
    state.timestamps.intake_completed_at = datetime.utcnow()
    state.timestamps.touch()

    return state


# Agent 3 pattern — writes only to impact_metrics:
#
#   def calculate_impact(state: ProjectState) -> ProjectState:
#       state.impact_metrics = ImpactMetrics(
#           impact_track=state.structured_intake.track,
#           reach_estimate=state.structured_intake.num_students_estimate,
#           partnership_count=len(state.structured_intake.community_partnerships),
#           community_score_total=14.5,
#           community_score_json={"reach": 3, "depth": 4, "equity": 3.5, "sustainability": 4},
#           methodology_notes="Reach scored by student count × partner multiplier.",
#       )
#       state.timestamps.impact_calculated_at = datetime.utcnow()
#       state.timestamps.touch()
#       return state
#
#
# Agent 4 pattern — writes only to reporting:
#
#   def generate_reporting(state: ProjectState) -> ProjectState:
#       lm = LogicModel(
#           inputs=["18 students", "6-week lab", "2 community partners"],
#           activities=["Composting trials", "Cafeteria presentation"],
#           outputs=["Compost system installed", "500 students reached"],
#           short_term_outcomes=["Increased food waste awareness"],
#           intermediate_outcomes=["Cafeteria policy change under review"],
#           equity_note="Title I school; 80% students qualify for free lunch.",
#       )
#       state.update_reporting(
#           logic_model=lm,
#           logic_model_text=lm.to_text(),
#           jotform_draft={
#               "Col 6": "18 students",
#               "Col 7": "Agriculture and Climate Change",
#               "Col 9": state.raw_input.raw_project_description,
#           },
#           funder_summary="Eighteen students at a Title I Montessori school...",
#           map_export_json={
#               "lat": 41.1177, "lng": -73.4082,
#               "lab_name": "Agriculture and Climate Change",
#               "grade_band": "elementary",
#               "num_students": 18,
#               "community_partnerships_count": 2,
#           }
#       )
#       state.timestamps.reporting_completed_at = datetime.utcnow()
#       return state

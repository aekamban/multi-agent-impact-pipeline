"""
TCImpact — Agent 3: Impact Calculator
======================================
Reads:  state.structured_intake  (StructuredIntake, written by Agent 2)
Writes: state.impact_metrics     (ImpactMetrics, consumed by Agent 4)

Rules:
- No LLM calls. All logic is deterministic math + rule-based scoring.
- Never touches state.reporting or state.structured_intake.
- Never rewrites project_state.py, agent2.py, or database.py.
- All EPA constants are named and cited inline.

Shared model:
  ImpactMetrics is imported directly from project_state.py.
  No local duplicate dataclass exists.

Key field type notes (project_state.ImpactMetrics):
  impact_track            Optional[Track]  -- use Track.A / Track.B enum
  behavior_change_proxy   str              -- human-readable label, not a numeric score
                                              Numeric score kept as internal _behavior_score
  epa_emissions_factor_used str            -- default "" (not Optional)
  co2_reduction_methodology str            -- default "" (not Optional)
  policy_influence_flag   bool             -- default False (not Optional)
  policy_description      str              -- default "" (not Optional)
  partnership_count       int              -- default 0 (not Optional)

Track routing (mirrors Agent 2 assignment):
  Track A -- En-ROADS lab only (~4/46 real submissions)
             CO2 reduction math with EPA emissions factors
  Track B -- All other 10 labs (~42/46 real submissions)
             Reach, behavior change proxy, community, policy metrics
"""

import json
import os
import sqlite3
from typing import Any, Optional

from project_state import ImpactMetrics, Track


# ─────────────────────────────────────────────────────────────────
# EPA EMISSIONS FACTORS
# Source: EPA GHG Equivalencies Calculator (2023)
# https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator
# All values in lbs CO2e per unit consumed.
# ─────────────────────────────────────────────────────────────────

# EPA eGRID 2022 national average -- 0.386 kg CO2e/kWh = 0.851 lbs/kWh
EPA_ELECTRICITY_LBS_PER_KWH: float = 0.851

# Natural gas -- 11.7 lbs CO2 per therm (EPA)
EPA_NATURAL_GAS_LBS_PER_THERM: float = 11.7

# Gasoline -- 19.6 lbs CO2 per gallon (EPA)
EPA_GASOLINE_LBS_PER_GALLON: float = 19.6

# Diesel -- 22.4 lbs CO2 per gallon (EPA)
EPA_DIESEL_LBS_PER_GALLON: float = 22.4

# Average passenger vehicle -- 404 g CO2/mile = 0.891 lbs/mile (EPA 2022)
EPA_CAR_LBS_PER_MILE: float = 0.891

# Tree sequestration -- 48 lbs CO2/year per urban tree (EPA)
EPA_TREE_LBS_CO2_PER_YEAR: float = 48.0

# Track A carbon target (from En-ROADS lab curriculum)
TRACK_A_TARGET_LBS: float = 10_000.0


# ─────────────────────────────────────────────────────────────────
# BEHAVIOR CHANGE PROXY RULES
# Maps project_type strings to a numeric score (0-10) used internally.
# The score drives awareness_scale and the human-readable
# behavior_change_proxy label written to ImpactMetrics (str field).
# Higher score = stronger evidence of lasting behavior change.
# ─────────────────────────────────────────────────────────────────

BEHAVIOR_CHANGE_SCORES: dict[str, int] = {
    "Energy reduction/efficiency":                    8,
    "Renewable energy installation":                  9,
    "Tree planting / reforestation":                  7,
    "Composting program":                             7,
    "Food waste reduction":                           6,
    "Transportation behavior change":                 7,
    "Recycling program":                              5,
    "School/community garden":                        6,
    "Awareness / communications campaign":            4,
    "Policy advocacy / letter writing":               5,
    "Habitat restoration / invasive species removal": 7,
    "Environmental trail / outdoor classroom":        5,
    "Nature journaling / citizen science":            4,
    "Youth engagement / club":                        6,
    "Curriculum integration / life cycle analysis":   5,
    "Other":                                          3,
}

# Sustained action bonus: project continues beyond the class period.
# Add 2 points to the numeric score (cap at 10).
SUSTAINED_ACTION_BONUS: int = 2

AWARENESS_SCALE_LABELS: dict[str, str] = {
    "high":   "High -- measurable, lasting behavior change expected",
    "medium": "Medium -- awareness raised, some sustained action likely",
    "low":    "Low -- awareness-level engagement; limited lasting change",
}


# ─────────────────────────────────────────────────────────────────
# INPUT PARSING HELPERS
# ─────────────────────────────────────────────────────────────────

def _coerce_bool(value: Any) -> bool:
    """
    Safely coerce a wide range of truthy inputs to bool.

    Truthy:  1, True, "1", "true", "yes"  (case-insensitive)
    Falsy:   0, False, "0", "false", "no", None, or anything else.

    Note: when intake comes from StructuredIntake.model_dump(), sustained_action
    and equity_flag are already Optional[bool] -- no coercion needed. This helper
    handles legacy dict inputs and test fixtures safely.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return False


def _safe_float(value: Any) -> float:
    """
    Safely parse a numeric value to float.

    Handles: "1,000", " 500 ", "10", 10, 10.5, None.
    Returns 0.0 for None, empty string, or unparseable input.
    Does not attempt NLP parsing ("about 100" -> 0.0).
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _safe_int(value: Any) -> int:
    """Round-trip through _safe_float; truncates to int."""
    return int(_safe_float(value))


def _intake_as_dict(structured_intake: Any) -> dict:
    """
    Normalize structured_intake to a plain dict regardless of source type.

    Handles:
      - Plain dict (tests or simple wrappers)
      - Pydantic v2 model (has model_dump()) -- the real StructuredIntake
      - Pydantic v1 model (has dict())
      - Dataclass or plain object (has __dict__)
      - None -> empty dict

    When StructuredIntake.model_dump() is called:
      - track becomes a Track enum instance (Track.A or Track.B)
      - community_partnerships becomes list[dict] with keys: name, partner_type, description
      - sustained_action and equity_flag are already Optional[bool]
    """
    if structured_intake is None:
        return {}
    if isinstance(structured_intake, dict):
        return structured_intake
    if hasattr(structured_intake, "model_dump"):
        return structured_intake.model_dump()
    if hasattr(structured_intake, "dict"):
        return structured_intake.dict()
    if hasattr(structured_intake, "__dict__"):
        return vars(structured_intake)
    return {}


def _awareness_label(score: int) -> str:
    if score >= 7:
        return AWARENESS_SCALE_LABELS["high"]
    elif score >= 4:
        return AWARENESS_SCALE_LABELS["medium"]
    else:
        return AWARENESS_SCALE_LABELS["low"]


def _behavior_proxy_label(project_type: str, score: int) -> str:
    """
    Build the human-readable string for ImpactMetrics.behavior_change_proxy.
    That field is str in project_state.ImpactMetrics (not a numeric int).
    Format: "<project_type> -- score <n>/10 (<awareness level>)"
    """
    level = _awareness_label(score).split("--")[0].strip()
    return f"{project_type} -- score {score}/10 ({level})"


# ─────────────────────────────────────────────────────────────────
# COMMUNITY SCORE RUBRIC (Track B)
# Four dimensions, each 0-25 points -> total 0-100
# ─────────────────────────────────────────────────────────────────

def _score_community(
    people_reached: int,
    partnership_count: int,
    sustained_action: bool,
    equity_flag: bool,
) -> dict:
    """
    Score community impact on four dimensions (each 0-25, total 0-100).

    Reach (0-25):
      500+ -> 25 | 200+ -> 20 | 100+ -> 15 | 50+ -> 10 | 10+ -> 5 | else -> 2
    Depth (0-25):
      sustained_action=True -> 25 | False -> 12
    Equity (0-25):
      equity_flag=True -> 25 | False -> 10
    Sustainability (0-25):
      3+ partners -> 25 | 2 -> 20 | 1 -> 12 | 0 -> 5
    """
    if people_reached >= 500:
        reach_score = 25
    elif people_reached >= 200:
        reach_score = 20
    elif people_reached >= 100:
        reach_score = 15
    elif people_reached >= 50:
        reach_score = 10
    elif people_reached >= 10:
        reach_score = 5
    else:
        reach_score = 2

    depth_score = 25 if sustained_action else 12
    equity_score = 25 if equity_flag else 10

    if partnership_count >= 3:
        sustainability_score = 25
    elif partnership_count == 2:
        sustainability_score = 20
    elif partnership_count == 1:
        sustainability_score = 12
    else:
        sustainability_score = 5

    total = reach_score + depth_score + equity_score + sustainability_score
    return {
        "reach": reach_score,
        "depth": depth_score,
        "equity": equity_score,
        "sustainability": sustainability_score,
        "total": total,
    }


# ─────────────────────────────────────────────────────────────────
# PARTNERSHIP RESOLUTION (Track B)
# ─────────────────────────────────────────────────────────────────

def _resolve_partnerships(intake: dict) -> tuple[int, list[str]]:
    """
    Resolve partnership count and partner name list from intake.

    Accepts any of:
      - community_partnerships       list[dict] from StructuredIntake.model_dump()
                                     each dict has keys: name, partner_type, description
      - community_partnerships_json  JSON string of [{name, ...}] (legacy/dict path)
      - community_partnerships_count explicit integer count

    Derivation rules:
      - If explicit count is present, use it (teacher may know of partners not
        yet named in the structured list -- explicit count takes precedence).
      - If no explicit count but a list exists, derive count from list length.
      - Partner names extracted from whichever list is available.

    Returns: (partnership_count: int, partner_names: list[str])
    """
    parsed_list: list = []

    # 1. Already-parsed list -- this is what model_dump() produces from StructuredIntake
    raw_list = intake.get("community_partnerships")
    if isinstance(raw_list, list):
        parsed_list = raw_list

    # 2. JSON string fallback for dict-based / legacy inputs
    if not parsed_list:
        raw_json = intake.get("community_partnerships_json")
        if raw_json:
            try:
                parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if isinstance(parsed, list):
                    parsed_list = parsed
            except (json.JSONDecodeError, TypeError):
                pass

    # Extract names
    partner_names: list[str] = []
    for p in parsed_list:
        if isinstance(p, dict):
            name = p.get("name", "")
        elif hasattr(p, "name"):
            name = getattr(p, "name", "")
        else:
            name = ""
        if name:
            partner_names.append(str(name))

    # Count: explicit wins; otherwise derive from list
    explicit_count = intake.get("community_partnerships_count")
    if explicit_count is not None:
        count = _safe_int(explicit_count)
    elif parsed_list:
        count = len(parsed_list)
    else:
        count = 0

    return count, partner_names


def _partner_narrative(partnership_count: int, partner_names: list[str]) -> str:
    """
    Build the partnership line for methodology notes.

    Rules:
      count == 0:                 "no community partners documented at this stage"
      count > 0, no names:       "2 community partner(s) identified"
      count == len(names):       "partnering with Name1 and Name2"
      count > len(names):        "5 community partners identified, including Name1 and Name2"
                                  (reflects teacher knowing of more partners than named)
    """
    if partnership_count == 0:
        return "no community partners documented at this stage"
    if not partner_names:
        return f"{partnership_count} community partner(s) identified"
    if len(partner_names) == 1:
        named_str = partner_names[0]
    else:
        named_str = ", ".join(partner_names[:-1]) + f" and {partner_names[-1]}"
    if partnership_count <= len(partner_names):
        return f"partnering with {named_str}"
    return f"{partnership_count} community partners identified, including {named_str}"


# ─────────────────────────────────────────────────────────────────
# TRACK A CALCULATOR
# ─────────────────────────────────────────────────────────────────

def calculate_track_a(intake: dict) -> ImpactMetrics:
    """
    Calculate CO2 reduction for Track A (En-ROADS lab) projects.

    Accepted intake fields (all optional -- handles missing gracefully):
      energy_kwh_reduced      -- kilowatt-hours of electricity saved
      natural_gas_therms      -- therms of natural gas saved
      gasoline_gallons        -- gallons of gasoline displaced
      diesel_gallons          -- gallons of diesel displaced
      car_miles_avoided       -- vehicle miles avoided
      trees_planted           -- number of trees planted
      carbon_lbs_estimated    -- explicit override when no factors provided
    """
    steps = []
    total_lbs = 0.0

    kwh = _safe_float(intake.get("energy_kwh_reduced"))
    if kwh > 0:
        lbs = round(kwh * EPA_ELECTRICITY_LBS_PER_KWH, 2)
        total_lbs += lbs
        steps.append({"step": "Electricity savings",
                       "input_value": f"{kwh} kWh",
                       "factor": f"{EPA_ELECTRICITY_LBS_PER_KWH} lbs CO2e/kWh (EPA eGRID 2022 national avg)",
                       "result_lbs": lbs})

    therms = _safe_float(intake.get("natural_gas_therms"))
    if therms > 0:
        lbs = round(therms * EPA_NATURAL_GAS_LBS_PER_THERM, 2)
        total_lbs += lbs
        steps.append({"step": "Natural gas savings",
                       "input_value": f"{therms} therms",
                       "factor": f"{EPA_NATURAL_GAS_LBS_PER_THERM} lbs CO2/therm (EPA)",
                       "result_lbs": lbs})

    gallons_gas = _safe_float(intake.get("gasoline_gallons"))
    if gallons_gas > 0:
        lbs = round(gallons_gas * EPA_GASOLINE_LBS_PER_GALLON, 2)
        total_lbs += lbs
        steps.append({"step": "Gasoline displacement",
                       "input_value": f"{gallons_gas} gallons",
                       "factor": f"{EPA_GASOLINE_LBS_PER_GALLON} lbs CO2/gallon (EPA)",
                       "result_lbs": lbs})

    gallons_diesel = _safe_float(intake.get("diesel_gallons"))
    if gallons_diesel > 0:
        lbs = round(gallons_diesel * EPA_DIESEL_LBS_PER_GALLON, 2)
        total_lbs += lbs
        steps.append({"step": "Diesel displacement",
                       "input_value": f"{gallons_diesel} gallons",
                       "factor": f"{EPA_DIESEL_LBS_PER_GALLON} lbs CO2/gallon (EPA)",
                       "result_lbs": lbs})

    miles = _safe_float(intake.get("car_miles_avoided"))
    if miles > 0:
        lbs = round(miles * EPA_CAR_LBS_PER_MILE, 2)
        total_lbs += lbs
        steps.append({"step": "Vehicle miles avoided",
                       "input_value": f"{miles} miles",
                       "factor": f"{EPA_CAR_LBS_PER_MILE} lbs CO2/mile (EPA 2022 avg passenger vehicle)",
                       "result_lbs": lbs})

    trees = _safe_int(intake.get("trees_planted"))
    if trees > 0:
        lbs = round(trees * EPA_TREE_LBS_CO2_PER_YEAR, 2)
        total_lbs += lbs
        steps.append({"step": "Tree planting (annual sequestration)",
                       "input_value": f"{trees} trees",
                       "factor": f"{EPA_TREE_LBS_CO2_PER_YEAR} lbs CO2/tree/year (EPA urban tree avg)",
                       "result_lbs": lbs})

    # Override: teacher-provided estimate when no individual factors entered
    override = _safe_float(intake.get("carbon_lbs_estimated"))
    if override > 0 and total_lbs == 0:
        total_lbs = override
        steps.append({"step": "Teacher-provided estimate (no individual factors entered)",
                       "input_value": f"{total_lbs} lbs",
                       "factor": "Teacher estimate accepted as-is",
                       "result_lbs": total_lbs})

    total_lbs = round(total_lbs, 2)
    target_met = (total_lbs >= TRACK_A_TARGET_LBS) if total_lbs > 0 else None
    factors_used = [s["step"] for s in steps]
    epa_label = "; ".join(factors_used) if factors_used else "No quantifiable factors provided"

    methodology_payload = json.dumps({
        "steps": steps,
        "total_co2_reduction_lbs": total_lbs,
        "target_lbs": TRACK_A_TARGET_LBS,
        "target_met": target_met,
        "epa_factors_used": epa_label,
        "note": (
            "All emissions factors from EPA GHG Equivalencies Calculator (2023). "
            "Calculations shown step-by-step to support student learning and funder transparency."
        ),
    }, indent=2)

    if total_lbs > 0:
        step_summary = ", ".join(s["step"].lower() for s in steps)
        methodology_text = (
            f"Students calculated CO2 reduction using EPA-standard emissions factors. "
            f"Activities included: {step_summary}. "
            f"Total estimated reduction: {total_lbs:,.0f} lbs CO2e "
            f"({'exceeds' if target_met else 'below'} the 10,000 lb class target). "
            f"Methodology is transparent and step-by-step, following En-ROADS curriculum guidance."
        )
    else:
        methodology_text = (
            "En-ROADS track project. No quantifiable emissions inputs provided at this time. "
            "Methodology will be updated as the project progresses."
        )

    return ImpactMetrics(
        impact_track=Track.A,
        co2_reduction_lbs=total_lbs if total_lbs > 0 else None,
        co2_reduction_methodology=methodology_payload,  # str field -- never None
        co2_target_met=target_met,
        epa_emissions_factor_used=epa_label,            # str field -- never None
        methodology_notes=methodology_text,
    )


# ─────────────────────────────────────────────────────────────────
# TRACK B CALCULATOR
# ─────────────────────────────────────────────────────────────────

def calculate_track_b(intake: dict) -> ImpactMetrics:
    """
    Calculate community impact metrics for Track B projects.

    Accepted intake fields (all optional -- handles missing gracefully):
      people_reached               -- explicit count from teacher
      num_students_estimate        -- Agent 2 normalized midpoint
      num_students_max             -- upper bound of student count range
      num_students_min             -- lower bound of student count range
      community_partnerships       -- list[dict] from StructuredIntake.model_dump()
      community_partnerships_json  -- JSON string of [{name, partner_type, ...}]
      community_partnerships_count -- explicit count
      sustained_action             -- bool / 1 / "yes" if project continues beyond class
      equity_flag                  -- bool / 1 / "yes" if underserved community served
      project_type                 -- string matching project_types table
      policy_influence_flag        -- bool / 1 if policy/advocacy outcome claimed
      policy_description           -- free text describing policy outcome

    Reach calculation (conservative, funder-defensible):
      Priority order:
        1. people_reached          -- explicit teacher-provided figure
        2. num_students_estimate   -- Agent 2 midpoint normalization
        3. num_students_max        -- upper bound
        4. num_students_min        -- lower bound
      Reach is NOT inflated by a partner proxy. The student count is the
      verifiable baseline; partnership value is captured in the community score
      sustainability dimension and partnership_count field.
      To add a partner proxy in future, introduce a dedicated intake field
      (e.g. community_audience_estimate) so funders can audit the assumption.
    """

    # ── People reached (priority order) ──────────────────────────
    people_reached = 0
    reach_source = "no student count available"

    for field_name, label in [
        ("people_reached",        "teacher-provided people_reached figure"),
        ("num_students_estimate", "Agent 2 normalized student estimate"),
        ("num_students_max",      "upper bound of student count range"),
        ("num_students_min",      "lower bound of student count range"),
    ]:
        val = _safe_int(intake.get(field_name))
        if val > 0:
            people_reached = val
            reach_source = label
            break

    # ── Community partnerships ────────────────────────────────────
    partnership_count, partner_names = _resolve_partnerships(intake)

    # ── Boolean fields ────────────────────────────────────────────
    # From real StructuredIntake, sustained_action and equity_flag are already
    # Optional[bool]. _coerce_bool handles legacy dict / test fixture inputs.
    sustained = _coerce_bool(intake.get("sustained_action"))
    equity = _coerce_bool(intake.get("equity_flag"))
    policy_flag = _coerce_bool(intake.get("policy_influence_flag"))

    # ── Behavior change proxy ─────────────────────────────────────
    project_type_str = intake.get("project_type") or "Other"
    _behavior_score = BEHAVIOR_CHANGE_SCORES.get(project_type_str, 3)
    if sustained:
        _behavior_score = min(10, _behavior_score + SUSTAINED_ACTION_BONUS)

    # behavior_change_proxy is a str field in ImpactMetrics (not int)
    behavior_change_proxy_label = _behavior_proxy_label(project_type_str, _behavior_score)
    awareness_scale = _awareness_label(_behavior_score)

    # ── Policy description ────────────────────────────────────────
    policy_desc = (intake.get("policy_description") or "").strip()

    # ── Community score ───────────────────────────────────────────
    community_scores = _score_community(
        people_reached=people_reached,
        partnership_count=partnership_count,
        sustained_action=sustained,
        equity_flag=equity,
    )

    # ── Methodology notes ─────────────────────────────────────────
    partner_line = _partner_narrative(partnership_count, partner_names)
    notes_parts = [
        f"Estimated reach: {people_reached:,} people ({reach_source}).",
        f"Community engagement: {partner_line}.",
        f"Behavior change: {behavior_change_proxy_label}.",
    ]
    if sustained:
        notes_parts.append("Project is expected to continue beyond the class period.")
    if equity:
        notes_parts.append("Project explicitly serves an underserved or Title I community.")
    if policy_flag and policy_desc:
        notes_parts.append(f"Policy outcome documented: {policy_desc}")
    notes_parts.append(
        f"Community impact score: {community_scores['total']}/100 "
        f"(reach {community_scores['reach']}, depth {community_scores['depth']}, "
        f"equity {community_scores['equity']}, sustainability {community_scores['sustainability']})."
    )

    return ImpactMetrics(
        impact_track=Track.B,
        reach_estimate=people_reached,
        behavior_change_proxy=behavior_change_proxy_label,  # str field
        awareness_scale=awareness_scale,
        partnership_count=partnership_count,
        policy_influence_flag=policy_flag,   # bool field, default False
        policy_description=policy_desc,      # str field, "" not None
        community_score_total=float(community_scores["total"]),
        community_score_json=community_scores,
        methodology_notes=" ".join(notes_parts),
    )


# ─────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def run_agent3(state: object) -> object:
    """
    Primary callable. Reads state.structured_intake, calculates impact
    metrics, writes to state.impact_metrics.

    Compatible with state.structured_intake as:
      - A real StructuredIntake Pydantic model (has model_dump())
      - A plain dict (for tests)
      - A Pydantic v1 model (has dict())
      - A dataclass or plain object (has __dict__)

    Uses state.update_impact_metrics() if available (real ProjectState),
    otherwise sets state.impact_metrics directly (_FakeState in tests).

    Does NOT write to state.reporting or state.structured_intake.
    Does NOT make any LLM calls.
    Returns the updated state object.
    """
    raw_intake = getattr(state, "structured_intake", None)
    intake: dict = _intake_as_dict(raw_intake)

    # Track may arrive as a Track enum (from model_dump) or a string (from dicts)
    track_val = intake.get("track")
    if isinstance(track_val, Track):
        track = track_val
    elif isinstance(track_val, str) and track_val:
        try:
            track = Track(track_val.upper())
        except ValueError:
            track = Track.B
    else:
        track = Track.B

    metrics = calculate_track_a(intake) if track == Track.A else calculate_track_b(intake)

    # Real ProjectState: use safe partial-update helper
    # Test _FakeState: set directly
    if hasattr(state, "update_impact_metrics"):
        state.update_impact_metrics(**metrics.model_dump())
    else:
        state.impact_metrics = metrics

    return state


# ─────────────────────────────────────────────────────────────────
# DB WRITE
# ─────────────────────────────────────────────────────────────────

def _bool_to_int(v: Optional[bool]) -> Optional[int]:
    """Convert Optional[bool] to 1/0/None for SQLite storage."""
    if v is None:
        return None
    return 1 if v else 0


def write_impact_to_db(project_id: int, metrics: ImpactMetrics, db_path: str = None) -> None:
    """
    Persist ImpactMetrics to the projects table (flags default to None).

    Prefer write_impact_to_db_with_flags() when sustained_action and
    equity_flag are known -- those fields are used by database.py
    get_impact_summary() for funder dashboard aggregates.
    """
    write_impact_to_db_with_flags(
        project_id=project_id,
        metrics=metrics,
        sustained_action=None,
        equity_flag=None,
        db_path=db_path,
    )


def write_impact_to_db_with_flags(
    project_id: int,
    metrics: ImpactMetrics,
    sustained_action: Optional[bool],
    equity_flag: Optional[bool],
    db_path: str = None,
) -> None:
    """
    Persist ImpactMetrics + funder flags to the projects table.

    sustained_action and equity_flag are read from state.structured_intake
    (not from ImpactMetrics -- they live on the intake side of the contract).
    They are written here as 1/0/None because database.py get_impact_summary()
    uses p.sustained_action and p.equity_flag in aggregate queries for the
    funder dashboard.

    COALESCE(?, column) pattern: only overwrites if the new value is non-NULL,
    so partial updates never blank out previously written flags.

    Track B extended metrics (behavior_change_proxy, awareness_scale,
    policy_influence_flag, policy_description, methodology_notes) do not have
    dedicated schema columns. They are stored in carbon_calculation_json under
    an "extended_metrics" key. If carbon_calculation_json already has content,
    it is merged (not overwritten). Agent 4 reads these from there.

    Raises ValueError if project_id does not exist in the database.
    """
    path = db_path or os.getenv("TCIMPACT_DB_PATH", "tcimpact.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        if metrics.impact_track == Track.A:
            cursor = conn.execute(
                """
                UPDATE projects SET
                    carbon_lbs_estimated     = ?,
                    carbon_calculation_json  = ?,
                    carbon_target_met        = ?,
                    sustained_action         = COALESCE(?, sustained_action),
                    equity_flag              = COALESCE(?, equity_flag),
                    updated_at               = datetime('now')
                WHERE id = ?
                """,
                (
                    metrics.co2_reduction_lbs,
                    metrics.co2_reduction_methodology or None,
                    _bool_to_int(metrics.co2_target_met),
                    _bool_to_int(sustained_action),
                    _bool_to_int(equity_flag),
                    project_id,
                )
            )

        else:  # Track B
            # Build extended_metrics for fields without schema columns
            extended_payload = {
                "extended_metrics": {
                    "behavior_change_proxy": metrics.behavior_change_proxy,
                    "awareness_scale":       metrics.awareness_scale,
                    "policy_influence_flag": metrics.policy_influence_flag,
                    "policy_description":    metrics.policy_description,
                    "methodology_notes":     metrics.methodology_notes,
                }
            }

            # Merge with any existing carbon_calculation_json (don't overwrite blindly)
            row = conn.execute(
                "SELECT carbon_calculation_json FROM projects WHERE id = ?", (project_id,)
            ).fetchone()

            if row and row[0]:
                try:
                    existing = json.loads(row[0])
                    existing.update(extended_payload)
                    merged_payload = json.dumps(existing)
                except (json.JSONDecodeError, TypeError):
                    merged_payload = json.dumps(extended_payload)
            else:
                merged_payload = json.dumps(extended_payload)

            cursor = conn.execute(
                """
                UPDATE projects SET
                    people_reached               = ?,
                    community_score_total        = ?,
                    community_score_json         = ?,
                    community_partnerships_count = ?,
                    carbon_calculation_json      = ?,
                    sustained_action             = COALESCE(?, sustained_action),
                    equity_flag                  = COALESCE(?, equity_flag),
                    updated_at                   = datetime('now')
                WHERE id = ?
                """,
                (
                    metrics.reach_estimate,
                    metrics.community_score_total,
                    json.dumps(metrics.community_score_json) if metrics.community_score_json else None,
                    metrics.partnership_count,
                    merged_payload,
                    _bool_to_int(sustained_action),
                    _bool_to_int(equity_flag),
                    project_id,
                )
            )

        if cursor.rowcount == 0:
            raise ValueError(
                f"write_impact_to_db: no project found with id={project_id}. "
                "Verify the project was inserted before calling Agent 3."
            )

        conn.commit()
    finally:
        conn.close()

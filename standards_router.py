"""
standards_router.py — Agent 1 Standards Lookup Engine (v3)

Changes from v2:
- extract_target_lab() parses lab name from free text so run_agent1()
  can pass target_lab without the caller doing it manually.
- _lookup_csv_rows() now applies real subject filtering for all systems
  (US subject fit, IB MYP/DP subjects, UK GCSE/A-Level subjects,
  Cambridge stage), not just US grade-band filtering.
- format_for_prompt() caps output to top-N labs to keep prompt size bounded.
- Standards block now includes target_lab prominently at the top when set.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
_CANDIDATE_ROOTS = [_HERE, _HERE / "documents"]

def _find_file(name: str) -> Optional[Path]:
    for root in _CANDIDATE_ROOTS:
        p = root / name
        if p.exists():
            return p
    return None

def _load_csv(name: str) -> list[dict]:
    p = _find_file(name)
    if not p:
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _load_json(name: str) -> dict:
    p = _find_file(name)
    if not p:
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

_US_ROWS  = _load_csv("learning_labs_US_standards_full_progression.csv")
_IB_ROWS  = _load_csv("learning_labs_IB_standards.csv")
_UK_ROWS  = _load_csv("learning_labs_UK_standards_with_KS2_KS3.csv")
_CAM_ROWS = _load_csv("learning_labs_cambridge_standards.csv")
_DB       = _load_json("standards_database.json")

_ROUTING_PATTERNS: list[dict] = _DB.get("routing", {}).get("patterns", [])
_NEVER_DO: list[str]          = _DB.get("agent1_routing_instructions", {}).get("never_do", [])
_FALLBACK_SCRIPT: str         = _DB.get("agent1_routing_instructions", {}).get(
    "fallback_script",
    "Could you tell me what curriculum system your school follows and what subject and grade you teach?"
)

_CSV_MAP = {"US": _US_ROWS, "IB": _IB_ROWS, "UK": _UK_ROWS, "Cambridge": _CAM_ROWS}

# All canonical lab names for text extraction
ALL_LAB_NAMES: list[str] = [
    "Agriculture & Climate Change", "Renewable Energy", "Civics & Climate Action",
    "Climate Justice & Equity", "Invasive Species", "Wildfires", "Floods & Droughts",
    "Sea Level Rise", "Climate Change & Health", "Climate Migration",
    "En-ROADS Climate Modeling",
]

# Aliases that appear in natural language but map to canonical names
_LAB_ALIASES: dict[str, str] = {
    "en-roads": "En-ROADS Climate Modeling",
    "enroads": "En-ROADS Climate Modeling",
    "agriculture": "Agriculture & Climate Change",
    "farming": "Agriculture & Climate Change",
    "renewable energy": "Renewable Energy",
    "solar": "Renewable Energy",
    "wind energy": "Renewable Energy",
    "civics": "Civics & Climate Action",
    "climate action": "Civics & Climate Action",
    "climate justice": "Climate Justice & Equity",
    "equity": "Climate Justice & Equity",
    "invasive species": "Invasive Species",
    "wildfires": "Wildfires",
    "wildfire": "Wildfires",
    "floods": "Floods & Droughts",
    "droughts": "Floods & Droughts",
    "sea level": "Sea Level Rise",
    "sea level rise": "Sea Level Rise",
    "health": "Climate Change & Health",
    "migration": "Climate Migration",
    "climate migration": "Climate Migration",
}


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class StandardsResult:
    curriculum_system: str
    stage: str
    confidence: float
    needs_clarification: bool
    target_lab: Optional[str] = None        # explicitly detected from free text
    matched_labs: list[str] = field(default_factory=list)
    lab_standards: dict[str, dict] = field(default_factory=dict)
    source_tables: list[str] = field(default_factory=list)
    routing_pattern_id: str = ""
    fallback_script: str = ""
    never_do_warnings: list[str] = field(default_factory=list)

    def best_lab_row(self, lab_name: str) -> dict:
        return self.lab_standards.get(lab_name, {})

    def all_lab_rows(self) -> list[tuple[str, dict]]:
        return [(lab, self.lab_standards[lab])
                for lab in self.matched_labs if lab in self.lab_standards]

    def format_for_prompt(self, max_labs: int = 4) -> str:
        """
        Render standards data for injection into teacher prompt.
        target_lab always appears first and in full.
        Remaining labs are capped at max_labs to keep prompt size bounded.
        """
        if self.needs_clarification:
            return f"STANDARDS LOOKUP: Insufficient context.\nASK THE TEACHER: {self.fallback_script}"

        lines = [
            "STANDARDS LOOKUP RESULT",
            f"  Curriculum system : {self.curriculum_system}",
            f"  Stage/band        : {self.stage}",
            f"  Routing confidence: {self.confidence:.0%}",
            f"  Source tables     : {', '.join(self.source_tables)}",
            f"  Pattern ID        : {self.routing_pattern_id}",
        ]
        if self.target_lab:
            lines.append(f"  ★ Target lab (from teacher message): {self.target_lab}")
        lines.append("")

        # Build ordered lab list: target first, then others up to max_labs
        ordered: list[tuple[str, dict]] = []
        if self.target_lab and self.target_lab in self.lab_standards:
            ordered.append((self.target_lab, self.lab_standards[self.target_lab]))
        for lab, row in self.all_lab_rows():
            if lab != self.target_lab:
                ordered.append((lab, row))
            if len(ordered) >= max_labs:
                break

        if not ordered:
            lines.append("(No matching lab data found for this teacher's context.)")
        else:
            for lab, row in ordered:
                prefix = "★ " if lab == self.target_lab else ""
                lines.append(f"LAB: {prefix}{lab}")
                for col, val in row.items():
                    if col != "Learning Lab" and val and val.strip():
                        lines.append(f"  {col}: {val.strip()}")
                lines.append("")

        if self.never_do_warnings:
            lines.append("CONSTRAINTS FOR THIS TEACHER (never violate):")
            for w in self.never_do_warnings:
                lines.append(f"  ⚠ {w}")

        return "\n".join(lines)


# ── Lab name extraction from free text ────────────────────────────────────────

def extract_target_lab(text: str) -> Optional[str]:
    """
    Extract a canonical lab name from teacher's free text.
    Checks full lab names first, then aliases.
    Returns canonical name or None.
    """
    text_lower = text.lower()

    # Full canonical name match (longest first to avoid partial matches)
    for lab in sorted(ALL_LAB_NAMES, key=len, reverse=True):
        if lab.lower() in text_lower:
            return lab

    # Alias match
    for alias, canonical in sorted(_LAB_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in text_lower:
            return canonical

    return None


# ── Routing helpers ────────────────────────────────────────────────────────────

def _match_routing_pattern(text: str) -> Optional[dict]:
    text_lower = text.lower()
    best = None
    best_conf = 0.0
    for pattern in _ROUTING_PATTERNS:
        match_cfg = pattern.get("match", {})
        if match_cfg.get("type") != "regex_any":
            continue
        for rx in match_cfg.get("patterns", []):
            try:
                if re.search(rx, text_lower, re.IGNORECASE):
                    conf = float(pattern.get("confidence", 0.7))
                    if conf > best_conf:
                        best_conf = conf
                        best = pattern
                    break
            except re.error:
                continue
    return best


def _infer_system_from_context(context: dict) -> tuple[str, str, float]:
    country = (context.get("country") or "").strip().upper()
    std     = (context.get("curriculum_standard") or "").strip()
    grade   = (context.get("grade_band") or "").strip().lower()

    if any(kw in std.upper() for kw in ["IB", "MYP", "DP", "PYP", "DIPLOMA"]):
        stage = "MYP" if "MYP" in std.upper() else ("DP" if "DP" in std.upper() else "IB")
        return "IB", stage, 0.85

    if any(kw in std.upper() for kw in ["CAMBRIDGE", "IGCSE", "AS/A", "CAIE"]):
        stage = "IGCSE" if "IGCSE" in std.upper() else "AS/A Level"
        return "Cambridge", stage, 0.85

    if any(kw in std.upper() for kw in ["GCSE", "A-LEVEL", "A LEVEL", "KS3", "KS4", "KS5"]) \
            or country in ("UK", "GB", "ENGLAND", "WALES", "SCOTLAND", "NORTHERN IRELAND"):
        stage = "GCSE" if "GCSE" in std.upper() else ("A-Level" if "A-LEVEL" in std.upper() else "KS3/4")
        return "UK", stage, 0.82

    all_fields_empty = not any([country, std, grade, context.get("subject_area", "")])
    if all_fields_empty:
        return "unknown", "unknown", 0.3

    has_us_signal = (
        country in ("US", "USA", "UNITED STATES") or
        any(kw in std.upper() for kw in
            ["NGSS", "CCSS", "C3", "NCTM", "CSTA", "NHES", "NCAS", "ACTFL", "ISTE"])
    )
    if has_us_signal:
        return "US", _grade_to_us_stage(grade), 0.80

    # Country set but no known standard — treat as US with low confidence
    if country and country not in ("US", "USA"):
        return "unknown", "unknown", 0.4

    return "US", _grade_to_us_stage(grade), 0.75


def _grade_to_us_stage(grade_band: str) -> str:
    grade_band = grade_band.lower()
    if any(k in grade_band for k in ["k-5", "elementary", "k-2", "3-5", "primary"]):
        return "3-5"
    if any(k in grade_band for k in ["middle", "6-8", "6th", "7th", "8th"]):
        return "6-8"
    if any(k in grade_band for k in ["high", "9-12", "9th", "10th", "11th", "12th", "ap "]):
        return "9-12"
    return "9-12"


def _stage_matches_csv_bands(stage: str, csv_bands: list) -> bool:
    if not stage:
        return True
    stage_map = {
        "9-12": {"9-10", "11-12", "9-12"},
        "6-8":  {"6-8"},
        "3-5":  {"3-5", "K-5"},
    }
    accepted = stage_map.get(stage, {stage})
    return any(b.strip() in accepted for b in csv_bands)


def _subject_matches_row(system: str, stage: str, subject: str, row: dict) -> bool:
    """
    Return True if this subject has a meaningful match in the CSV row.
    Applied as a real filter (not soft/no-op) for all systems.
    An empty subject always returns True (no filtering).
    """
    if not subject:
        return True
    s = subject.lower().strip()

    if system == "US":
        subject_fit = row.get("Subject Fit", "").lower()
        ap_fit      = row.get("AP Course Fit", "").lower()
        # Match on any significant word (4+ chars) from subject string
        words = [w for w in s.split() if len(w) >= 4]
        return any(w in subject_fit or w in ap_fit for w in words) if words else True

    if system == "IB":
        if "MYP" in stage.upper():
            field = row.get("MYP Subjects", "").lower()
        else:
            field = row.get("DP Subjects", "").lower()
        words = [w for w in s.split() if len(w) >= 4]
        return any(w in field for w in words) if words else True

    if system == "UK":
        if "GCSE" in stage.upper() or "KS" in stage.upper():
            field = row.get("GCSE Subjects", "").lower()
        else:
            field = row.get("A Level Subjects", "").lower()
        words = [w for w in s.split() if len(w) >= 4]
        return any(w in field for w in words) if words else True

    if system == "Cambridge":
        if "IGCSE" in stage.upper():
            field = row.get("IGCSE/IGCSE (9–1)", "").lower()
        elif "primary" in stage.lower() or "stage" in stage.lower():
            field = row.get("Primary", "").lower()
        else:
            field = row.get("AS/A Level", "").lower()
        words = [w for w in s.split() if len(w) >= 4]
        return any(w in field for w in words) if words else True

    return True  # unknown system: no filtering


def _lookup_csv_rows(
    system: str,
    stage: str,
    subject: str,
    lab_filter: Optional[list[str]] = None,
) -> dict[str, dict]:
    """
    Query correct CSV for labs matching system/stage/subject.
    Applies real subject filtering for all systems.
    Falls back to grade-band-only match if subject filter eliminates everything.
    Falls back to all-labs if grade-band filter also eliminates everything.

    Routing fidelity note:
      US filtering is the tightest: grade band comes from a structured 'US Grade Bands'
      column with explicit values (e.g. '9-10', '6-8'), so band exclusion is precise.
      IB/UK/Cambridge filtering is subject-keyword based against free-text subject
      columns — it correctly narrows results but does not enforce stage exclusion the
      way US grade-band filtering does. A Cambridge Primary teacher asking about a
      DP-level lab will not be blocked by stage. This is acceptable for POC; tighter
      stage gating for non-US systems is a production improvement.
    """
    rows = _CSV_MAP.get(system, [])
    if not rows:
        return {}

    def _row_passes_grade(row: dict) -> bool:
        if system != "US" or not stage:
            return True
        bands = [b.strip() for b in row.get("US Grade Bands", "").split(";")]
        return _stage_matches_csv_bands(stage, bands)

    def _row_passes_subject(row: dict) -> bool:
        return _subject_matches_row(system, stage, subject, row)

    def _collect(grade_filter: bool, subj_filter: bool) -> dict[str, dict]:
        result = {}
        for row in rows:
            lab_name = row.get("Learning Lab", "").strip()
            if not lab_name:
                continue
            if lab_filter and lab_name not in lab_filter:
                continue
            if grade_filter and not _row_passes_grade(row):
                continue
            if subj_filter and not _row_passes_subject(row):
                continue
            result[lab_name] = dict(row)
        return result

    # Try strictest first, relax progressively
    result = _collect(grade_filter=True,  subj_filter=True)
    if not result:
        result = _collect(grade_filter=True,  subj_filter=False)
    if not result:
        result = _collect(grade_filter=False, subj_filter=False)
    return result


def _select_never_do_warnings(system: str, subject: str) -> list[str]:
    warnings = []
    for rule in _NEVER_DO:
        rule_lower = rule.lower()
        if system == "US":
            if "ap " in rule_lower or "state" in rule_lower or "social studies" in rule_lower:
                warnings.append(rule)
        elif system == "IB":
            if "ib " in rule_lower or "criteria" in rule_lower:
                warnings.append(rule)
        elif system == "UK":
            if "gcse" in rule_lower or "exam board" in rule_lower or "scottish" in rule_lower:
                warnings.append(rule)
        elif system == "Cambridge":
            if "cambridge" in rule_lower:
                warnings.append(rule)
    return warnings[:3]


# ── Public API ─────────────────────────────────────────────────────────────────

def route_teacher(
    context: dict,
    free_text: str = "",
    target_lab: Optional[str] = None,
) -> StandardsResult:
    """
    Route a teacher to the correct standards CSV and return structured data.

    target_lab is auto-extracted from free_text if not provided explicitly.
    The result always has target_lab set when one is detectable.
    """
    subject = (context.get("subject_area") or "").strip()
    grade   = (context.get("grade_band") or "").strip()

    # Auto-extract target lab from free text if not passed explicitly
    if target_lab is None and free_text:
        target_lab = extract_target_lab(free_text)

    # Step 1: regex pattern matching on free text
    matched_pattern = _match_routing_pattern(free_text) if free_text else None

    if matched_pattern and float(matched_pattern.get("confidence", 0)) >= 0.75:
        normalized    = matched_pattern.get("normalized", {})
        system        = normalized.get("curriculum_system", "US")
        stage         = normalized.get("stage", _grade_to_us_stage(grade))
        conf          = float(matched_pattern.get("confidence", 0.8))
        recommended   = matched_pattern.get("recommended_labs", [])
        table_name    = matched_pattern.get("tables_to_query", [""])[0]
        pattern_id    = matched_pattern.get("id", "")
    else:
        system, stage, conf = _infer_system_from_context(context)
        recommended   = []
        table_name    = f"learning_labs_{system.lower()}_standards.csv"
        pattern_id    = "context_inferred"

    # Step 2: clarification check
    if conf < 0.75 and system == "unknown":
        return StandardsResult(
            curriculum_system="unknown", stage="unknown", confidence=conf,
            needs_clarification=True, target_lab=target_lab,
            fallback_script=_FALLBACK_SCRIPT,
        )

    # Step 3: CSV lookup — target lab always included if set
    # Build lab_filter: start from recommended, ensure target_lab is in it
    if recommended:
        lab_filter = list(recommended)
        if target_lab and target_lab not in lab_filter:
            lab_filter.insert(0, target_lab)  # prepend target
    elif target_lab:
        lab_filter = None  # look up everything, target_lab ordering handled in format_for_prompt
    else:
        lab_filter = None

    lab_standards = _lookup_csv_rows(system, stage, subject, lab_filter=lab_filter)

    # Ensure target_lab is always present even if filtering excluded it
    if target_lab and target_lab not in lab_standards:
        direct = _lookup_csv_rows(system, stage, "", lab_filter=[target_lab])
        if direct:
            lab_standards.update(direct)

    never_do = _select_never_do_warnings(system, subject)

    # Ordered matched_labs: target first
    all_labs = list(lab_standards.keys())
    if target_lab and target_lab in all_labs:
        all_labs = [target_lab] + [l for l in all_labs if l != target_lab]

    return StandardsResult(
        curriculum_system=system,
        stage=stage,
        confidence=conf,
        needs_clarification=False,
        target_lab=target_lab,
        matched_labs=all_labs,
        lab_standards=lab_standards,
        source_tables=[table_name],
        routing_pattern_id=pattern_id,
        fallback_script=_FALLBACK_SCRIPT,
        never_do_warnings=never_do,
    )


# ── Quick test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        ("US HS Chem → Renewable Energy",
         {"subject_area": "Chemistry", "grade_band": "high school",
          "curriculum_standard": "NGSS", "country": "US"},
         "How does the Renewable Energy lab fit into my NGSS chemistry curriculum?"),
        ("IB MYP ESS",
         {"subject_area": "Environmental Systems", "grade_band": "MYP",
          "curriculum_standard": "IB MYP", "country": "Switzerland"},
         "I teach IB MYP Environmental Systems"),
        ("UK GCSE Geography",
         {"subject_area": "Geography", "grade_band": "GCSE",
          "curriculum_standard": "UK GCSE", "country": "UK"},
         "I teach GCSE Geography — which lab fits best?"),
        ("Empty → clarification",
         {"subject_area": "", "grade_band": "", "curriculum_standard": "", "country": ""},
         ""),
    ]
    for label, ctx, text in cases:
        print(f"\n{'='*55}\n{label}")
        r = route_teacher(ctx, free_text=text)
        print(f"system={r.curriculum_system} stage={r.stage} conf={r.confidence:.0%} "
              f"target={r.target_lab} clarif={r.needs_clarification} labs={len(r.matched_labs)}")
        if r.matched_labs:
            print("Top labs:", r.matched_labs[:3])

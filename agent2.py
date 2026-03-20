"""
agent2.py
TCImpact — Agent 2: Intake & Structuring

Takes a messy teacher submission and returns a populated ProjectState.

Four responsibilities:
    1. match_lab_name()        — fuzzy match informal lab name → canonical
    2. normalize_student_count() — parse messy text → min/max/estimate
    3. assign_track()          — Track A (En-ROADS) or Track B (all others)
    4. extract_partners()      — narrative text → list[CommunityPartner]

Public entry point:
    process_submission(raw_input, teacher_context) -> ProjectState

Design rules:
    - match_lab_name() is pure Python but optionally queries the DB alias table
      (cached via lru_cache — one DB hit per process, graceful offline fallback)
    - normalize_student_count() and assign_track() are pure Python, no DB, always fast
    - extract_partners() uses LLM when LIVE_LLM=1; falls back to regex heuristic otherwise
    - parse_grade_reference() is pure Python; returns normalized grade band from any curriculum system
    - infer_project_type(), infer_sustained_action(), infer_equity_flag() are pure Python,
      deterministic, offline-safe — no LLM required
    - Never writes to project_state.impact_metrics or project_state.reporting
    - Never rewrites project_state.py or project_state_adapter.py
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Optional

from project_state import (
    CommunityPartner,
    GradeBand,
    Phase,
    ProjectState,
    RawInput,
    SchoolType,
    StructuredIntake,
    TeacherContext,
    Track,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

# Canonical lab registry: name → (db_id, track, thematic_topic)
# IDs match the INSERT order in schema.sql (1-indexed, stable for POC).
# If the DB is available, match_lab_name() will prefer the live alias table.
CANONICAL_LABS: dict[str, dict] = {
    "Climate Impacts and Solutions with En-ROADS": {
        "id": 1, "track": Track.A, "thematic_topic": "Climate Solutions & Modeling"
    },
    "Agriculture and Climate Change": {
        "id": 2, "track": Track.B, "thematic_topic": "Food & Land Use"
    },
    "Civics Climate Action": {
        "id": 3, "track": Track.B, "thematic_topic": "Policy & Civic Action"
    },
    "Climate Justice and Equity": {
        "id": 4, "track": Track.B, "thematic_topic": "Justice & Equity"
    },
    "Renewable Energy": {
        "id": 5, "track": Track.B, "thematic_topic": "Energy"
    },
    "Wildfires": {
        "id": 6, "track": Track.B, "thematic_topic": "Climate Impacts"
    },
    "Floods and Droughts": {
        "id": 7, "track": Track.B, "thematic_topic": "Climate Impacts"
    },
    "Sea Level Rise": {
        "id": 8, "track": Track.B, "thematic_topic": "Climate Impacts"
    },
    "Invasive Species": {
        "id": 9, "track": Track.B, "thematic_topic": "Ecosystems"
    },
    "Climate Change and Health": {
        "id": 10, "track": Track.B, "thematic_topic": "Health"
    },
    "Climate Migration": {
        "id": 11, "track": Track.B, "thematic_topic": "Justice & Equity"
    },
}

# Keyword shortcuts that are too short or ambiguous for difflib alone.
# Maps lowercase keyword/phrase fragments → canonical lab name.
# Ordered from most-specific to least-specific (first match wins).
KEYWORD_SHORTCUTS: list[tuple[str, str]] = [
    ("en-roads", "Climate Impacts and Solutions with En-ROADS"),
    ("enroads", "Climate Impacts and Solutions with En-ROADS"),
    ("en roads", "Climate Impacts and Solutions with En-ROADS"),
    ("carbon simulation", "Climate Impacts and Solutions with En-ROADS"),
    ("co2 simulation", "Climate Impacts and Solutions with En-ROADS"),
    ("agri", "Agriculture and Climate Change"),
    ("farm", "Agriculture and Climate Change"),
    ("food", "Agriculture and Climate Change"),
    ("compost", "Agriculture and Climate Change"),
    ("garden", "Agriculture and Climate Change"),
    ("civic", "Civics Climate Action"),
    ("policy", "Civics Climate Action"),
    ("government", "Civics Climate Action"),
    ("legislat", "Civics Climate Action"),
    ("justice", "Climate Justice and Equity"),
    ("equity", "Climate Justice and Equity"),
    ("renew", "Renewable Energy"),
    ("solar", "Renewable Energy"),
    ("wind energy", "Renewable Energy"),
    ("wildfire", "Wildfires"),
    ("fire", "Wildfires"),
    ("flood", "Floods and Droughts"),
    ("drought", "Floods and Droughts"),
    ("water scarcity", "Floods and Droughts"),
    ("sea level", "Sea Level Rise"),
    ("coastal", "Sea Level Rise"),
    ("ocean rise", "Sea Level Rise"),
    ("invasive", "Invasive Species"),
    ("species", "Invasive Species"),
    ("health", "Climate Change and Health"),
    ("migrat", "Climate Migration"),
    ("refugee", "Climate Migration"),
    ("displacement", "Climate Migration"),
]

LOW_CONFIDENCE_THRESHOLD = 0.80

# Partner type classification keywords
PARTNER_TYPE_KEYWORDS: dict[str, list[str]] = {
    "government": ["city", "town", "county", "state", "federal", "municipality",
                   "department of", "agency", "EPA", "DOE", "mayor"],
    "university": ["university", "college", "institute", "professor", "faculty",
                   "research center", "lab", "academic"],
    "NGO": ["foundation", "nonprofit", "non-profit", "conservancy", "alliance",
            "coalition", "initiative", "society", "association", "trust", "fund"],
    "business": ["company", "corp", "inc", "llc", "ltd", "store", "market",
                 "restaurant", "firm", "enterprise", "co."],
    "school": ["school", "district", "classroom", "cafeteria", "principal",
               "teacher", "student", "PTA", "PTO"],
    "community": ["community center", "library", "church", "mosque", "synagogue",
                  "neighborhood", "local", "residents", "volunteers"],
    "media": ["newspaper", "news", "tv", "radio", "podcast", "media", "press"],
}


# ─────────────────────────────────────────
# 1. FUZZY LAB NAME MATCHING
# ─────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_aliases_from_db() -> dict[str, tuple[str, int, float]]:
    """
    Try to load alias table from SQLite. Cached per process (lru_cache).
    Returns dict: alias_lower → (canonical_name, canonical_lab_id, confidence)
    Returns empty dict if DB is unavailable (tests, offline use).
    """
    try:
        from database import get_connection
        conn = get_connection()
        rows = conn.execute("""
            SELECT a.alias, l.lab_name, a.canonical_lab_id, a.confidence
            FROM lab_name_aliases a
            JOIN learning_labs l ON a.canonical_lab_id = l.id
        """).fetchall()
        conn.close()
        return {
            row["alias"].lower(): (row["lab_name"], row["canonical_lab_id"], row["confidence"])
            for row in rows
        }
    except Exception as e:
        logger.debug(f"DB alias table unavailable, using in-memory only: {e}")
        return {}


def _difflib_best_match(normalized: str) -> tuple[str, float]:
    """
    Use SequenceMatcher to find the closest canonical lab name.
    Returns (canonical_name, confidence_score).
    """
    best_name = ""
    best_score = 0.0
    for canonical in CANONICAL_LABS:
        score = SequenceMatcher(None, normalized, canonical.lower()).ratio()
        if score > best_score:
            best_score = score
            best_name = canonical
    return best_name, round(best_score, 3)


def match_lab_name(raw_lab_name: str) -> tuple[str, int, float]:
    """
    Match an informal lab name to a canonical TCI lab name.
    Safely handles None, empty string, or whitespace-only input.

    Strategy (in order):
        0. Exact canonical name match (score = 1.0)
        1. DB alias table exact match (confidence from table, cached)
        2. Keyword shortcut match (confidence = 0.90)
        3. difflib fuzzy match against canonical names (confidence = ratio)

    Returns:
        (canonical_lab_name, canonical_lab_id, confidence)
        confidence < LOW_CONFIDENCE_THRESHOLD (0.80) should trigger a warning.
        Returns ("", 0, 0.0) for None/empty input.
    """
    # Guard: treat None, empty, or whitespace-only as no input
    if not raw_lab_name or not raw_lab_name.strip():
        return "", 0, 0.0

    normalized = raw_lab_name.strip().lower()

    # 0. Exact canonical name — highest priority, score = 1.0
    for canonical in CANONICAL_LABS:
        if normalized == canonical.lower():
            meta = CANONICAL_LABS[canonical]
            return canonical, meta["id"], 1.0

    # 1. DB alias table — exact match on normalized alias
    db_aliases = _load_aliases_from_db()
    if normalized in db_aliases:
        name, lab_id, conf = db_aliases[normalized]
        return name, lab_id, conf

    # Also try stripping common filler words before alias check
    stripped = re.sub(r'\b(the|a|an|lab|learning|module|unit|project|our|my)\b', '', normalized).strip()
    if stripped in db_aliases:
        name, lab_id, conf = db_aliases[stripped]
        return name, lab_id, round(conf * 0.97, 3)  # slight penalty for needing strip

    # 2. Keyword shortcuts — substring match
    for keyword, canonical_name in KEYWORD_SHORTCUTS:
        if keyword in normalized:
            meta = CANONICAL_LABS[canonical_name]
            return canonical_name, meta["id"], 0.90

    # 3. difflib fuzzy match
    best_name, best_score = _difflib_best_match(normalized)
    if best_name:
        return best_name, CANONICAL_LABS[best_name]["id"], best_score

    # No match found
    return "", 0, 0.0


# ─────────────────────────────────────────
# 2. STUDENT COUNT NORMALIZATION
# ─────────────────────────────────────────

def normalize_student_count(raw_text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Parse messy student count text into (min, max, estimate).

    Handles:
        "30"                           → (30, 30, 30)
        "25 students"                  → (25, 25, 25)
        "about 30"                     → (None, None, 30)
        "10-25"                        → (10, 25, 17)
        "10-25, K-8th"                 → (10, 25, 17)   ← grade band stripped
        "9-12"  (alone)                → (None, None, None)  ← ambiguous grade band
        "6-8"   (alone)                → (None, None, None)
        "grades 9-12"                  → (None, None, None)  ← explicit grade word
        "500+"                         → (500, None, 500)
        "2 classes of 30 students"     → (None, None, 30)   ← prefers student-labelled number
        "3 sections, 90 students total"→ (None, None, 90)
        "6 groups, 24 students"        → (None, None, 24)
        "K-8th"                        → (None, None, None)
        ""                             → (None, None, None)

    Returns:
        (num_students_min, num_students_max, num_students_estimate)
    """
    if not raw_text or not raw_text.strip():
        return None, None, None

    text = raw_text.strip()

    # ── Pre-pass: prefer number directly labelled as students/kids/total ─────
    # Avoids returning class count instead of student count for
    # "2 classes of 30 students" or "3 sections, 90 students total".
    _student_label = re.search(
        r'(\d+)\s*(?:students?|kids?|pupils?|learners?|participants?|graders?)\b',
        text, re.IGNORECASE
    )
    _total_label = re.search(
        r'(\d+)\s*(?:total|in\s+total|students?\s+total)\b',
        text, re.IGNORECASE
    )
    preferred_val: Optional[int] = None
    if _student_label:
        preferred_val = int(_student_label.group(1))
    elif _total_label:
        preferred_val = int(_total_label.group(1))

    # ── Grade-band strip ─────────────────────────────────────────────────────
    # Remove grade-band expressions so they don't pollute number extraction.
    # Rules: only strip when context makes grade intent unambiguous.
    text_clean = text

    # K-N ranges: K-12, K-8, K-5 — "K" before a dash is always a grade
    text_clean = re.sub(r'\b(K|kindergarten)\s*[-\u2013]\s*\d{1,2}(?:st|nd|rd|th)?\b',
                        '', text_clean, flags=re.IGNORECASE)
    # Ordinal grade ranges: 9th-12th, 6th-8th
    text_clean = re.sub(r'\b\d{1,2}(?:st|nd|rd|th)\s*[-\u2013]\s*\d{1,2}(?:st|nd|rd|th)\b',
                        '', text_clean, flags=re.IGNORECASE)
    # Explicit grade word AFTER range: "6-8 grade(s)", "9-12 grade"
    text_clean = re.sub(r'\b\d{1,2}\s*[-\u2013]\s*\d{1,2}\s+grades?\b',
                        '', text_clean, flags=re.IGNORECASE)
    # Explicit grade word BEFORE range: "grades 9-12", "grade 6-8"
    text_clean = re.sub(r'\bgrades?\s+\d{1,2}\s*[-\u2013]\s*\d{1,2}\b',
                        '', text_clean, flags=re.IGNORECASE)
    # Single "Year N" or "Grade N" references (not bare numbers)
    text_clean = re.sub(r'\b(?:year|grade)\s+\d{1,2}\b',
                        '', text_clean, flags=re.IGNORECASE)

    text_clean = text_clean.strip()

    # ── Ambiguous bare grade-band guard ──────────────────────────────────────
    # If the ENTIRE remaining text is a small N-M range (both 1-12),
    # treat it as a grade range, not a student count. "9-12" alone = grades 9-12.
    # Only applies when text_clean is JUST the range (no other context).
    _remaining = text_clean.rstrip('.,; ')
    _bare = re.fullmatch(r'(\d{1,2})\s*[-\u2013]\s*(\d{1,2})', _remaining)
    if _bare:
        lo_g, hi_g = int(_bare.group(1)), int(_bare.group(2))
        if 1 <= lo_g <= 12 and 1 <= hi_g <= 12:
            return None, None, None

    # ── Return preferred (student-labelled) value if found ───────────────────
    # If the student-labelled number is the ONLY number in the text (no range,
    # no approximation word), treat it as exact: (val, val, val).
    # e.g. '25 students' → (25,25,25); '2 classes of 30 students' → (None,None,30)
    if preferred_val is not None:
        _all_nums = re.findall(r'\d+', text_clean)
        _is_only_num = len(_all_nums) == 1 and _all_nums[0] == str(preferred_val)
        if _is_only_num:
            return preferred_val, preferred_val, preferred_val
        return None, None, preferred_val

    # ── "500+" lower bound only ───────────────────────────────────────────────
    _plus = re.search(r'(\d+)\s*\+', text_clean)
    if _plus:
        val = int(_plus.group(1))
        return val, None, val

    # ── Range: "10-25", "10 to 25", "10–25" ──────────────────────────────────
    _range = re.search(r'(\d+)\s*(?:-|\u2013|to)\s*(\d+)', text_clean)
    if _range:
        lo, hi = int(_range.group(1)), int(_range.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi, (lo + hi) // 2

    # ── Approximate: "about 30", "~45", "approximately 50" ───────────────────
    _approx = re.search(r'(?:about|around|approximately|roughly|approx\.?|~)\s*(\d+)',
                        text_clean, re.IGNORECASE)
    if _approx:
        return None, None, int(_approx.group(1))

    # ── Plain number (last resort) ────────────────────────────────────────────
    _plain = re.search(r'\b(\d+)\b', text_clean)
    if _plain:
        val = int(_plain.group(1))
        return val, val, val

    return None, None, None


# ─────────────────────────────────────────
# 3. TRACK ASSIGNMENT
# ─────────────────────────────────────────

def assign_track(canonical_lab_name: str) -> Optional[Track]:
    """
    Assign Track A (En-ROADS / carbon) or Track B (all other labs).
    Returns None only for empty input.
    Unknown lab names that are not in CANONICAL_LABS default to Track B
    (safe fallback — all non-En-ROADS labs are Track B).
    """
    if not canonical_lab_name:
        return None
    meta = CANONICAL_LABS.get(canonical_lab_name)
    if meta:
        return meta["track"]
    # Fallback: if "en-roads" appears anywhere in the name, it's Track A
    if "en-roads" in canonical_lab_name.lower() or "enroads" in canonical_lab_name.lower():
        return Track.A
    return Track.B


# ─────────────────────────────────────────
# 3.5 GRADE REFERENCE NORMALIZATION
# ─────────────────────────────────────────


def _grade_number_to_band(grade_num: int) -> str:
    """Map a US grade number (K=0, 1-12) to elementary/middle/high."""
    if grade_num <= 5:
        return "elementary"
    if grade_num <= 8:
        return "middle"
    return "high"


class GradeReference:
    """
    Result of parse_grade_reference(). Lightweight container, no Pydantic overhead.
    """
    __slots__ = ("raw", "normalized_grade", "grade_band")

    def __init__(self, raw: str, normalized_grade: str, grade_band: str):
        self.raw = raw                            # original string as passed in
        self.normalized_grade = normalized_grade  # e.g. "9", "K", "6-8", "MYP3"
        self.grade_band = grade_band              # elementary | middle | high | mixed | unknown

    def __repr__(self) -> str:
        return f"GradeReference(raw={self.raw!r}, normalized={self.normalized_grade!r}, band={self.grade_band!r})"


def parse_grade_reference(raw: str) -> "GradeReference":
    """
    Detect school system and normalize a grade reference.

    normalized_grade field semantics:
      - US grades:   bare number string, e.g. "9", or range "6-8"
      - Kindergarten: "K"
      - K-ranges:    "K-12", "K-8", "K-5"  (span from Kindergarten to grade N)
      - IB MYP:      "MYP3" (not converted to US equivalent — retains original system label)
      - IB DP:       "11" or "12" (DP1/DP2 mapped to US high-school equivalent)
      - UK Year:     "Year6", "Year7" etc. (prefixed to avoid confusion with US grade numbers)

    Examples:
        "Year 6"    → normalized="Year6",  band="elementary"
        "Year 7"    → normalized="Year7",  band="middle"
        "MYP 3"     → normalized="MYP3",   band="middle"
        "DP 1"      → normalized="11",     band="high"
        "Grade 7"   → normalized="7",      band="middle"
        "9th grade" → normalized="9",      band="high"
        "K"         → normalized="K",      band="elementary"
        "K-12"      → normalized="K-12",   band="mixed"
        "K-8"       → normalized="K-8",    band="mixed"
        "K-5"       → normalized="K-5",    band="elementary"
        "6-8"       → normalized="6-8",    band="middle"
        "9-12"      → normalized="9-12",   band="high"
        ""          → normalized="",       band="unknown"

    Returns GradeReference with .raw, .normalized_grade, .grade_band.
    """
    if not raw or not raw.strip():
        return GradeReference(raw=raw or "", normalized_grade="", grade_band="unknown")

    text = raw.strip()

    # ── K-N ranges BEFORE single-K check to avoid misclassifying "K-12" as elementary ──
    # Matches: K-12, K-8, K-5, Kindergarten-12, etc.
    k_range_match = re.search(
        r"\b(K|Kindergarten)\s*[-\u2013]\s*(\d{1,2})(?:st|nd|rd|th)?\b",
        text, re.IGNORECASE
    )
    if k_range_match:
        hi = int(k_range_match.group(2))
        hi_band = _grade_number_to_band(hi)
        # K=elementary; if hi is also elementary the whole range is elementary,
        # otherwise it spans bands → mixed.
        band = "elementary" if hi_band == "elementary" else "mixed"
        return GradeReference(raw=raw, normalized_grade=f"K-{hi}", grade_band=band)

    # ── Single Kindergarten ──────────────────────────────────────────────────
    if re.search(r"\b(K|Kindergarten)\b", text, re.IGNORECASE):
        return GradeReference(raw=raw, normalized_grade="K", grade_band="elementary")

    # ── IB DP: DP1=grade 11, DP2=grade 12 ───────────────────────────────────
    dp_match = re.search(r"\bDP\s*([12])\b", text, re.IGNORECASE)
    if dp_match:
        grade = 10 + int(dp_match.group(1))
        return GradeReference(raw=raw, normalized_grade=str(grade), grade_band="high")

    # ── IB MYP: MYP1=grade 6, MYP2=7, MYP3=8, MYP4=9, MYP5=10 ─────────────
    myp_match = re.search(r"\bMYP\s*([1-5])\b", text, re.IGNORECASE)
    if myp_match:
        myp_num = int(myp_match.group(1))
        us_equiv = myp_num + 5
        band = _grade_number_to_band(us_equiv)
        return GradeReference(raw=raw, normalized_grade=f"MYP{myp_num}", grade_band=band)

    # ── UK Year groups ───────────────────────────────────────────────────────
    # normalized_grade is prefixed "Year N" (not bare number) to avoid
    # false interpretation as a US grade by downstream consumers.
    year_match = re.search(r"\bYear\s*(\d{1,2})\b", text, re.IGNORECASE)
    if year_match:
        year_num = int(year_match.group(1))
        if year_num <= 6:
            band = "elementary"
        elif year_num <= 9:
            band = "middle"
        else:
            band = "high"
        return GradeReference(raw=raw, normalized_grade=f"Year{year_num}", grade_band=band)

    # ── Numeric grade range: "6-8", "9-12", "6th-8th" ───────────────────────
    range_match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s*[-\u2013]\s*(\d{1,2})(?:st|nd|rd|th)?\b",
        text
    )
    if range_match:
        lo, hi = int(range_match.group(1)), int(range_match.group(2))
        lo_band = _grade_number_to_band(lo)
        hi_band = _grade_number_to_band(hi)
        band = lo_band if lo_band == hi_band else "mixed"
        return GradeReference(raw=raw, normalized_grade=f"{lo}-{hi}", grade_band=band)

    # ── Single US grade: "Grade 7", "9th", "7th grade" ──────────────────────
    single_match = re.search(r"\b(?:grade\s*)?(\d{1,2})(?:st|nd|rd|th)?\b", text, re.IGNORECASE)
    if single_match:
        grade_num = int(single_match.group(1))
        if 1 <= grade_num <= 12:
            return GradeReference(
                raw=raw,
                normalized_grade=str(grade_num),
                grade_band=_grade_number_to_band(grade_num),
            )

    return GradeReference(raw=raw, normalized_grade="", grade_band="unknown")


# ─────────────────────────────────────────
# 4. COMMUNITY PARTNER EXTRACTION
# ─────────────────────────────────────────

def _classify_partner_type(name: str) -> str:
    """
    Classify a partner name into a partner_type string using keyword matching.
    Returns the first matching type, or "community" as default.
    """
    name_lower = name.lower()
    for ptype, keywords in PARTNER_TYPE_KEYWORDS.items():
        if any(kw.lower() in name_lower for kw in keywords):
            return ptype
    return "community"


def _extract_partners_heuristic(narrative: str) -> list[CommunityPartner]:
    """
    Regex/heuristic extraction of community partners from narrative text.
    Used when LIVE_LLM=0 or as fallback.

    Looks for:
        - "partnered with X"
        - "in partnership with X"
        - "collaborated with X"
        - "worked with X"
        - "supported by X"
        - "X donated / sponsored / provided"
        - Comma/semicolon separated lists after trigger phrases
    """
    partners: list[CommunityPartner] = []
    seen: set[str] = set()

    # Trigger phrase patterns → capture what follows up to punctuation/and/or
    trigger_patterns = [
        r'(?:partnered?|partnership)\s+with\s+([^.,;\n]+)',
        r'(?:collaborated?|collaboration)\s+with\s+([^.,;\n]+)',
        r'(?:worked?|working)\s+with\s+([^.,;\n]+)',
        r'(?:supported?\s+by)\s+([^.,;\n]+)',
        r'(?:sponsored?\s+by)\s+([^.,;\n]+)',
        r'(?:funded?\s+by)\s+([^.,;\n]+)',
        r'(?:donated?\s+by)\s+([^.,;\n]+)',
        r'(?:in\s+collaboration\s+with)\s+([^.,;\n]+)',
        r'(?:community\s+partner[s]?)[:\s]+([^.\n]+)',
        r'(?:local\s+partner[s]?)[:\s]+([^.\n]+)',
        r'(?:organization[s]?)[:\s]+([^.\n]+)',
    ]

    for pattern in trigger_patterns:
        for match in re.finditer(pattern, narrative, flags=re.IGNORECASE):
            raw_names = match.group(1).strip()
            # Split on commas and semicolons first.
            # Only split on "and" when it clearly separates two short standalone phrases
            # (≤4 words on each side, neither side contains another "and").
            # This prevents splitting org names like "Boys and Girls Club".
            comma_parts = re.split(r'\s*(?:,|;)\s*', raw_names)
            parts = []
            for cp in comma_parts:
                cp = cp.strip()
                and_match = re.search(r'\band\b', cp, flags=re.IGNORECASE)
                if and_match:
                    left = cp[:and_match.start()].strip()
                    right = cp[and_match.end():].strip()
                    left_words = left.split()
                    right_words = right.split()
                    # Only split on "and" if both sides are short and neither has another "and"
                    left_clean = ' '.join(left_words).lower()
                    right_clean = ' '.join(right_words).lower()
                    safe_to_split = (
                        1 <= len(left_words) <= 3
                        and 1 <= len(right_words) <= 3
                        and 'and' not in left_clean
                        and 'and' not in right_clean
                    )
                    if safe_to_split:
                        parts.extend([left, right])
                    else:
                        parts.append(cp)  # keep whole phrase intact
                else:
                    parts.append(cp)
            for part in parts:
                name = part.strip().rstrip('.,;')
                # Filter noise: too short, stopwords, pronouns
                if len(name) < 3:
                    continue
                if name.lower() in {"the", "a", "an", "our", "their", "we", "us", "them"}:
                    continue
                name_key = name.lower()
                if name_key not in seen:
                    seen.add(name_key)
                    partners.append(CommunityPartner(
                        name=name,
                        partner_type=_classify_partner_type(name),
                    ))

    return partners


def _extract_partners_llm(narrative: str) -> list[CommunityPartner]:
    """
    LLM-based partner extraction using Azure OpenAI.
    Called only when LIVE_LLM=1.
    Returns list[CommunityPartner] parsed from structured JSON response.
    Falls back to heuristic if LLM call fails.
    """
    try:
        from langchain_openai import AzureChatOpenAI
        import json

        llm = AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4-1"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            temperature=0,
        )

        prompt = f"""You are extracting community partners from a teacher's project description.

Extract all organizations, businesses, government agencies, universities, or community groups
that this teacher or their students worked with, partnered with, or received support from.

Return ONLY a JSON array. Each element must have exactly these keys:
  "name": string (the organization's name as written)
  "partner_type": one of: government, university, NGO, business, school, community, media
  "description": string (one sentence about their role, or empty string if unclear)

If no partners are mentioned, return an empty array: []
Do not include the teacher's own school as a partner unless explicitly named as an external collaborator.

Text to analyze:
\"\"\"
{narrative}
\"\"\"

JSON array only, no other text:"""

        response = llm.invoke(prompt)
        raw = response.content.strip()

        # Strip markdown fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\s*```$', '', raw)

        parsed = json.loads(raw)
        return [
            CommunityPartner(
                name=p.get("name", "").strip(),
                partner_type=p.get("partner_type", "community"),
                description=p.get("description", ""),
            )
            for p in parsed
            if p.get("name", "").strip()
        ]

    except Exception as e:
        logger.debug(f"LLM partner extraction unavailable, using heuristic: {e}")
        return _extract_partners_heuristic(narrative)


def extract_partners(narrative: str) -> list[CommunityPartner]:
    """
    Extract community partners from narrative text.
    Uses LLM when LIVE_LLM=1; heuristic otherwise.
    """
    if not narrative or not narrative.strip():
        return []
    use_llm = os.getenv("LIVE_LLM", "0") == "1"
    if use_llm:
        return _extract_partners_llm(narrative)
    return _extract_partners_heuristic(narrative)


# ─────────────────────────────────────────
# 5. INFERENCE HELPERS — deterministic, offline-safe
# ─────────────────────────────────────────

def _is_title1(teacher_context: TeacherContext) -> bool:
    """
    Normalize title1_status to a boolean.
    Handles: "yes", "Yes", "YES", True, 1, and any other truthy string variant.
    Returns False for any value that does not clearly mean yes.
    """
    raw = teacher_context.title1_status
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw == 1
    if isinstance(raw, str):
        return raw.strip().lower() == "yes"
    return False


def _safe_lower(*parts: Optional[str]) -> str:
    """
    Safely join and lowercase an arbitrary number of string parts.
    None values and empty strings are silently skipped.
    Returns a single lowercased string safe for keyword matching.
    """
    return " ".join(p for p in parts if p and p.strip()).lower()


def infer_project_type(project_description: Optional[str], lab_name: Optional[str]) -> str:
    """
    Map free-text project description to one of 16 canonical project_type strings.
    Uses keyword matching on combined description + lab_name text.
    Returns "Other" if no match found.
    Ordered from most-specific to least-specific (first match wins).
    Safe against None or empty inputs.

    Trigger design notes:
      - "presentation" and "display" alone are NOT sufficient triggers for
        "Awareness / communications campaign" because they appear in many
        unrelated contexts (science fair, class presentation, etc.).
        They require co-occurrence with "awareness" or "campaign".
      - "curriculum" alone is NOT sufficient for "Curriculum integration /
        life cycle analysis"; it must co-occur with "life cycle" or "lifecycle"
        because almost every submission involves curriculum in some sense.
      - "poster" is kept as a standalone trigger: in TCI submissions a poster
        is almost always a public-facing awareness artifact.
    """
    text = _safe_lower(project_description, lab_name)

    if any(k in text for k in ["compost", "composting"]):
        return "Composting program"
    if any(k in text for k in ["solar", "panels", "renewable energy", "wind turbine"]):
        return "Renewable energy installation"
    if any(k in text for k in ["tree planting", "reforestation", "replant"]) or (
        "tree" in text and ("plant" in text or "trees" in text)
    ):
        return "Tree planting / reforestation"
    if any(k in text for k in ["food waste", "waste reduction"]):
        return "Food waste reduction"
    if "recycl" in text:
        return "Recycling program"
    if (
        any(k in text for k in ["school garden", "community garden",
                                 "planting vegetable", "growing vegetable",
                                 "grew vegetable"])
        or ("garden" in text and "grow" in text)
        or ("garden" in text and "plant" in text)
    ):
        return "School/community garden"
    if any(k in text for k in ["letter to", "city council", "policy advocacy",
                                "advocacy", "advocate", "petition", "legislation",
                                "letter writing"]):
        return "Policy advocacy / letter writing"
    # "presentation" and "display" require co-occurrence with awareness/campaign
    # to avoid false positives on generic class presentations.
    if any(k in text for k in ["awareness campaign", "social media campaign", "awareness"]):
        return "Awareness / communications campaign"
    if "poster" in text:
        return "Awareness / communications campaign"
    if ("presentation" in text or "display" in text) and (
        "campaign" in text or "public" in text or "community" in text
    ):
        return "Awareness / communications campaign"
    if any(k in text for k in ["habitat", "invasive", "restoration",
                                "native plant", "invasive species"]):
        return "Habitat restoration / invasive species removal"
    if any(k in text for k in ["trail", "outdoor classroom"]):
        return "Environmental trail / outdoor classroom"
    if any(k in text for k in ["citizen science", "nature journaling",
                                "nature journal", "journaling"]):
        return "Nature journaling / citizen science"
    if any(k in text for k in ["youth club", "student club", "youth group",
                                "student group", "youth engagement",
                                "environmental club"]):
        return "Youth engagement / club"
    # "curriculum" alone is too broad — require life-cycle co-occurrence.
    if any(k in text for k in ["life cycle", "lifecycle", "life-cycle analysis"]):
        return "Curriculum integration / life cycle analysis"
    if "curriculum" in text and "life cycle" not in text and "lifecycle" not in text:
        pass  # fall through to "Other" rather than over-classifying
    if any(k in text for k in ["carpool", "carpooling", "bike to school",
                                "walk to school", "transit",
                                "transportation behavior"]):
        return "Transportation behavior change"
    if any(k in text for k in ["energy audit", "energy efficiency", "led lights",
                                "electricity reduction", "energy reduction"]):
        return "Energy reduction/efficiency"
    return "Other"


def infer_sustained_action(
    project_description: Optional[str],
    additional_notes: Optional[str],
) -> Optional[bool]:
    """
    Return True if the project continues beyond the class period.
    Return False if it was clearly a one-off event.
    Return None if there is insufficient signal.
    Safe against None or empty inputs.

    Signal design notes:
      - "as a result" was intentionally excluded as a standalone trigger: it is
        too common in general causal language ("as a result of our research, we
        learned...") and fires false positives without additional context.
        The compound phrase "now has ... as a result" is strong; "now has" alone
        already fires True, which covers that case.
      - "installed" is kept because physical infrastructure implies permanence.
      - "annual" / "every year" signal institutionalisation beyond a single class period.
    """
    text = _safe_lower(project_description, additional_notes)

    sustained_signals = [
        "ongoing", "continues", "will continue", "permanent", "installed",
        "now has", "adopted", "still running",
        "every year", "annual", "long-term", "maintained",
    ]
    one_off_signals = [
        "one-time", "one day", "single event", "presentation only",
        "just presented", "completed",
    ]

    if any(s in text for s in sustained_signals):
        return True
    if any(s in text for s in one_off_signals):
        return False
    return None


def infer_equity_flag(
    teacher_context: TeacherContext,
    project_description: Optional[str],
    additional_notes: Optional[str] = None,
) -> Optional[bool]:
    """
    Return True if there is clear evidence of serving an underserved community.
    Return False if evidence clearly suggests otherwise.
    Return None if there is insufficient signal to decide.

    Signal sources (in priority order):
      1. teacher_context.title1_status — normalised via _is_title1(); "yes"/"YES"/True/1
         all count. Title I always returns True, overriding school type.
      2. Equity keywords in project_description or additional_notes.
      3. School type heuristic (POC only):
           PRIVATE or MONTESSORI + no Title I + no equity keywords → False.
           This is a lightweight POC heuristic, not a definitive determination.
           Private/Montessori schools CAN serve underserved communities, but
           without a positive signal we conservatively assume they do not.
           A Title I flag or explicit keyword always overrides this.

    Checks both project_description and additional_notes for equity keywords,
    because teachers often mention community context in the notes field.
    Safe against None or empty inputs.
    """
    text = _safe_lower(project_description, additional_notes)

    equity_keywords = [
        "underserved", "low-income", "title i", "title 1",
        "food desert", "environmental justice", "frontline", "marginalized",
        "tribal", "indigenous", "refugee", "immigrant community",
    ]
    has_equity_keywords = any(k in text for k in equity_keywords)

    # Title I is the strongest signal — always returns True.
    # _is_title1() normalises "yes", "YES", True, 1 safely.
    if _is_title1(teacher_context):
        return True

    if has_equity_keywords:
        return True

    # POC heuristic: private / Montessori schools with no positive equity signal
    # are conservatively assumed not to serve underserved communities.
    # This can be upgraded with real data in production.
    private_types = {SchoolType.PRIVATE, SchoolType.MONTESSORI}
    if (
        teacher_context.school_type in private_types
        and not _is_title1(teacher_context)
        and not has_equity_keywords
    ):
        return False

    return None


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def process_submission(
    raw_input: RawInput,
    teacher_context: Optional[TeacherContext] = None,
) -> ProjectState:
    """
    Take a raw teacher submission and return a fully structured ProjectState.

    Agent 2 writes:
        - state.structured_intake  (lab match, student count, track, partners, grade_band,
                                    project_type, sustained_action, equity_flag)
        - state.teacher_context    (passed through or defaulted)
        - state.warnings           (low confidence flags)
        - state.phase              (advances to PLANNING)
        - state.timestamps         (intake_completed_at)

    Agent 2 never touches:
        - state.impact_metrics
        - state.reporting
        - state.db_ids             (set later by project_state_adapter.py)

    Args:
        raw_input:        RawInput with teacher's unprocessed form fields
        teacher_context:  Optional TeacherContext (from pre-survey / session record)

    Returns:
        ProjectState with structured_intake fully populated
    """
    _teacher_context = teacher_context or TeacherContext()

    state = ProjectState(
        raw_input=raw_input,
        teacher_context=_teacher_context,
    )

    # ── Step 1: Fuzzy lab name matching ──────────────────────────────
    canonical_name, canonical_id, confidence = match_lab_name(raw_input.raw_lab_name)

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        state.add_warning(
            f"Low confidence lab match ({confidence:.0%}) for \"{raw_input.raw_lab_name}\". "
            f"Best guess: \"{canonical_name}\". Please confirm with teacher."
        )
        state.flag_low_confidence("canonical_lab_name")

    if not canonical_name:
        state.add_warning(
            f"Could not match \"{raw_input.raw_lab_name}\" to any known TCI lab. "
            "Manual review required."
        )

    # ── Step 2: Track assignment ──────────────────────────────────────
    # assign_track() always returns A or B for any non-empty name; None only for empty
    track = assign_track(canonical_name) if canonical_name else None

    # ── Step 3: Student count normalization ───────────────────────────
    s_min, s_max, s_estimate = normalize_student_count(raw_input.raw_student_count_text)

    if s_estimate is None and raw_input.raw_student_count_text.strip():
        state.add_warning(
            f"Could not parse student count from \"{raw_input.raw_student_count_text}\". "
            "Manual review recommended."
        )
        state.flag_low_confidence("num_students_estimate")

    # ── Step 4: Community partner extraction ──────────────────────────
    # Combine both fields: partners may be mentioned only in the project description
    partner_narrative_parts = [
        raw_input.raw_community_partners,
        raw_input.raw_project_description,
    ]
    partner_narrative = "\n\n".join(p for p in partner_narrative_parts if p and p.strip())
    partners = extract_partners(partner_narrative)

    # ── Step 5: Pull thematic topic from canonical lab registry ───────
    thematic_topic = ""
    if canonical_name and canonical_name in CANONICAL_LABS:
        thematic_topic = CANONICAL_LABS[canonical_name].get("thematic_topic", "")

    # ── Step 6: Grade band normalization ────────────────────────────
    # Source priority:
    #   a) raw_student_count_text  — teachers often include grade info here
    #      e.g. "30, grades 9-12" or "25 students, K-5"
    #   b) raw_additional_notes    — secondary free-text field
    # The resulting grade_band string is mapped to the GradeBand enum.
    # TeacherContext.school_locale / school_type / country are NOT mirrored
    # into StructuredIntake — downstream agents should read them from
    # state.teacher_context directly to avoid duplication.
    _grade_sources = [
        raw_input.raw_student_count_text,
        raw_input.raw_additional_notes,
    ]
    grade_band = GradeBand.UNKNOWN
    for _gsrc in _grade_sources:
        if not _gsrc or not _gsrc.strip():
            continue
        _gr = parse_grade_reference(_gsrc)
        if _gr.grade_band and _gr.grade_band != "unknown":
            _band_map = {
                "elementary": GradeBand.ELEMENTARY,
                "middle":     GradeBand.MIDDLE,
                "high":       GradeBand.HIGH,
                "mixed":      GradeBand.MIXED,
            }
            grade_band = _band_map.get(_gr.grade_band, GradeBand.UNKNOWN)
            break  # first non-unknown result wins

    # ── Assemble structured_intake ────────────────────────────────────
    state.structured_intake = StructuredIntake(
        canonical_lab_name=canonical_name,
        canonical_lab_id=canonical_id if canonical_id else None,
        lab_match_confidence=confidence,
        track=track,
        num_students_min=s_min,
        num_students_max=s_max,
        num_students_estimate=s_estimate,
        num_students_display=raw_input.raw_student_count_text,
        thematic_topic=thematic_topic,
        community_partnerships=partners,
        grade_band=grade_band,
        project_type=infer_project_type(
            raw_input.raw_project_description,
            canonical_name,
        ),
        sustained_action=infer_sustained_action(
            raw_input.raw_project_description,
            raw_input.raw_additional_notes,
        ),
        equity_flag=infer_equity_flag(
            _teacher_context,
            raw_input.raw_project_description,
            raw_input.raw_additional_notes,
        ),
    )

    # ── Finalize state ────────────────────────────────────────────────
    state.phase = Phase.PLANNING
    state.timestamps.intake_completed_at = datetime.utcnow()
    state.timestamps.touch()

    return state

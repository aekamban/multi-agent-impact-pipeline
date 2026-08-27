"""
evaluate_extraction.py

A small evaluation harness for Agent 2's community partner extraction
(extract_partners in agent2.py), built around a question the existing test
suite doesn't answer: not "does this work on one example," but "how
accurate and how consistent is it, with a number I can put a confidence
interval on."

Two modes:
  --mode heuristic   Runs the regex/heuristic extractor (no API key needed,
                      works right now, offline). This is the always-on
                      fallback path in production too.
  --mode llm         Runs the real Azure OpenAI extraction (needs
                      LIVE_LLM=1 and real credentials in .env). Each gold
                      example is run REPEAT_N times so we can measure
                      self-consistency, not just one-shot accuracy.
                      temperature=0 does not guarantee the same output on
                      every call, and for a funder-facing report, knowing
                      whether the same narrative can produce a different
                      partner list on a re-run matters as much as knowing
                      whether it got the right answer once.

Two separate numbers are reported for a reason: accuracy against the gold
set tells you if the model is right, self-consistency tells you if it's
reliable. A model can be one without the other, and conflating them hides
which problem you actually have.

Wilson score intervals are used instead of a normal approximation because
the gold set here is intentionally small (this is a POC evaluation set,
not a production-scale benchmark) and Wilson stays well-behaved near 0%
and 100%, where a normal approximation breaks down.
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from math import sqrt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- gold set
# Each example: narrative text + the partners a human reviewer would expect
# to be extracted. Matching is by name (case-insensitive) plus partner_type;
# description text is not scored, since it's free-form summary and
# shouldn't be held to exact wording.
GOLD = [
    {
        "narrative": (
            "Our class partnered with the Riverside Food Bank to set up a "
            "composting program, and the city's Department of Public Works "
            "helped us install the bins."
        ),
        "expected": [
            {"name": "Riverside Food Bank", "partner_type": "community"},
            {"name": "Department of Public Works", "partner_type": "government"},
        ],
    },
    {
        "narrative": (
            "Students collaborated with State University's environmental "
            "science department to test water samples from the local creek."
        ),
        "expected": [
            {"name": "State University", "partner_type": "university"},
        ],
    },
    {
        "narrative": (
            "We worked independently, no outside groups were involved in "
            "this project."
        ),
        "expected": [],
    },
    {
        "narrative": (
            "The project was supported by GreenFuture NGO, who donated "
            "seedlings, and we also worked with the local hardware store "
            "on discounted supplies."
        ),
        "expected": [
            {"name": "GreenFuture NGO", "partner_type": "NGO"},
            {"name": "local hardware store", "partner_type": "business"},
        ],
    },
    {
        "narrative": (
            "Our school newspaper covered the project, and the mayor's "
            "office sent a representative to our final presentation."
        ),
        "expected": [
            {"name": "school newspaper", "partner_type": "media"},
            {"name": "mayor's office", "partner_type": "government"},
        ],
    },
    {
        "narrative": (
            "In partnership with the town recycling center, students "
            "audited cafeteria waste for six weeks."
        ),
        "expected": [
            {"name": "town recycling center", "partner_type": "government"},
        ],
    },
    {
        "narrative": "Students built a rain garden on school grounds.",
        "expected": [],
    },
    {
        "narrative": (
            "We collaborated with the Sierra Club chapter and a local "
            "solar installation company to research renewable energy "
            "options for our district."
        ),
        "expected": [
            {"name": "Sierra Club", "partner_type": "NGO"},
            {"name": "local solar installation company", "partner_type": "business"},
        ],
    },
]


# ---------------------------------------------------------------- scoring
def _norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def match_partners(predicted, expected):
    """Set-based match on (normalized name, partner_type). Returns
    (true_positives, false_positives, false_negatives) counts for one
    example, since a single accuracy number can't distinguish "missed a
    partner" from "invented one," and those are different failure modes
    with different consequences for a funder-facing report."""
    pred_set = {(_norm(p.name), p.partner_type) for p in predicted}
    exp_set = {(_norm(e["name"]), e["partner_type"]) for e in expected}
    tp = len(pred_set & exp_set)
    fp = len(pred_set - exp_set)
    fn = len(exp_set - pred_set)
    return tp, fp, fn


def wilson_interval(successes, n, z=1.96):
    """95% Wilson score interval for a binomial proportion. Stays valid at
    the small n and near-0%/100% rates this evaluation set produces, unlike
    a normal-approximation interval."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denom
    half = (z * sqrt((p * (1 - p) + z ** 2 / (4 * n)) / n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class Metrics:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self):
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self):
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self):
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def run_heuristic():
    from agent2 import _extract_partners_heuristic

    total = Metrics(0, 0, 0)
    print(f"{'example':<60} tp  fp  fn")
    for ex in GOLD:
        predicted = _extract_partners_heuristic(ex["narrative"])
        tp, fp, fn = match_partners(predicted, ex["expected"])
        total.tp += tp
        total.fp += fp
        total.fn += fn
        label = ex["narrative"][:57] + "..." if len(ex["narrative"]) > 60 else ex["narrative"]
        print(f"{label:<60} {tp:>3} {fp:>3} {fn:>3}")

    print()
    print(f"precision: {total.precision:.3f}  recall: {total.recall:.3f}  f1: {total.f1:.3f}")
    n = total.tp + total.fp
    lo, hi = wilson_interval(total.tp, n) if n else (0.0, 0.0)
    print(f"precision 95% CI (Wilson, n={n}): [{lo:.3f}, {hi:.3f}]")
    print()
    print("This is the always-on fallback path (no API key needed). It's a")
    print("useful floor to know, since it's what every submission falls back")
    print("to if the LLM call fails or LIVE_LLM=0 is set.")


def run_llm(repeat_n=5):
    if os.getenv("LIVE_LLM") != "1":
        print("Set LIVE_LLM=1 and real Azure credentials in .env to run this mode.")
        print("(This sandbox has no Azure API access, so this path can only be")
        print(" validated structurally here, not run for real numbers.)")
        return

    from agent2 import _extract_partners_llm

    total = Metrics(0, 0, 0)
    consistent = 0
    for ex in GOLD:
        runs = [_extract_partners_llm(ex["narrative"]) for _ in range(repeat_n)]
        run_sets = [frozenset((_norm(p.name), p.partner_type) for p in r) for r in runs]
        is_consistent = len(set(run_sets)) == 1
        consistent += int(is_consistent)

        # Score against the first run for accuracy; self-consistency is
        # tracked separately above, deliberately not blended into one number.
        tp, fp, fn = match_partners(runs[0], ex["expected"])
        total.tp += tp
        total.fp += fp
        total.fn += fn

    n_examples = len(GOLD)
    cons_lo, cons_hi = wilson_interval(consistent, n_examples)
    print(f"accuracy  -> precision {total.precision:.3f}  recall {total.recall:.3f}  f1 {total.f1:.3f}")
    print(f"self-consistency across {repeat_n} repeated calls per example: "
          f"{consistent}/{n_examples} ({consistent / n_examples:.1%})")
    print(f"self-consistency 95% CI (Wilson): [{cons_lo:.3f}, {cons_hi:.3f}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["heuristic", "llm"], default="heuristic")
    ap.add_argument("--repeat-n", type=int, default=5,
                    help="Repeated calls per example in --mode llm, for self-consistency.")
    args = ap.parse_args()

    if args.mode == "heuristic":
        run_heuristic()
    else:
        run_llm(args.repeat_n)

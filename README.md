# TCImpact: Multi-Agent Impact Measurement System

**A four-agent LLM system (LangChain, Azure OpenAI GPT-4.1, RAG over program curriculum) that turns free-text program submissions from an international climate-education nonprofit into funder-ready, evidence-tier impact reporting, replacing a year-end form nobody filled out on time.**

## The problem

The organization trains thousands of educators across dozens of countries to run "Learning Labs," climate education units that end in a student-led Action Project. The only outcome data collection mechanism was a single year-end form. Teachers were overwhelmed, submissions arrived late or incomplete, and the organization had no formalized measurement framework capable of producing the evidence-tier outcome data that major funders require. A newly funded initiative also needed structured project data to feed a public impact map, which the existing form couldn't supply.

This system replaces the year-end form with a tool teachers and students actually use *during* the program. It collects the same information passively, in context, across three phases (planning, implementation, analysis), and turns it directly into structured, methodologically transparent reporting.

## Architecture

Four agents, each owning one stage of the pipeline, orchestrated with LangChain over Azure OpenAI (chat + `text-embedding-3-large`), with a FAISS vector store for RAG over the program's own curriculum documents.

| Agent | Role |
|---|---|
| **1: Curriculum & Coaching** | RAG over the full curriculum library. Helps teachers map a Learning Lab onto their existing subject and standards (NGSS, IB MYP/DP, UK GCSE/A-Level, Cambridge) so adoption doesn't require rewriting their syllabus, which was the single biggest adoption barrier identified with program staff. In student mode, it uses Socratic questioning (never direct answers) to help groups strengthen their project ideas, plus step-by-step math scaffolding for students doing carbon-impact calculations who hit math anxiety. Hard guardrails: never collects PII, never gives medical, legal, or school-administration advice. |
| **2: Intake & Structuring** | Turns messy free text into structured data. Fuzzy-matches informal lab names against a canonical alias table seeded from real historical submissions, normalizes qualitative fields ("10 to 25 students, K to 8th" becomes a structured min/max), extracts community partnerships from narrative text, and applies a 5-dimension rubric (reach, depth, equity, sustainability, fidelity) that's designed not to penalize brief submissions unfairly. |
| **3: Impact Calculator** | Computes outcomes two different ways depending on project type: EPA-methodology CO2 reduction with fully shown, step-by-step math for carbon-focused projects, and reach, behavior-change, and policy-outcome metrics for the much larger share of projects (in real submission data) centered on awareness, community action, or policy rather than a carbon target. Methodology is always shown. That's non-negotiable, both for funder credibility and for the students learning the math. |
| **4: Funder Reporting** | Scores community impact on 4 dimensions, generates an EPA logic-model-structured summary (Inputs, Activities, Outputs, Short/Intermediate Outcomes, Equity Note), auto-drafts the year-end form submission mapped to its exact fields, and exports structured per-project JSON for the organization's public impact map. Powers a password-protected funder-facing dashboard. |

Records stay mutable throughout all three phases instead of locking at submission, so a project's data reflects where it actually stands, not a snapshot frozen at whatever point a form happened to get filled out.

## What's real about this

This was built directly against the organization's actual constraints, not a synthetic scenario. The rubric design, the lab-name alias table, and the split between carbon-target projects and broader impact projects are seeded from real historical program submissions, and the reporting output is structured specifically to match funders' actual evidence requirements and the year-end form's actual fields. The POC runs on SQLite locally, and production deployment targets the organization's own Azure tenant.

510 tests cover the four agents and their integration adapter (structuring, calculation, and reporting logic, not just mocked LLM calls). They check things like whether rubric scoring avoids penalizing minimal submissions, whether student-count parsing handles the real range of qualitative formats seen in actual data, and whether generated funder summaries stay traceable back to their source input.

## Evaluating the extraction step

I originally built this in March 2026. Since then, coursework on statistically rigorous model evaluation (treating "does it work" as a measurement question with real uncertainty, not a single anecdotal check) pushed me to go back and actually evaluate one of the LLM-dependent pieces properly instead of trusting it because it looked fine on a few examples.

`evaluate_extraction.py` is a small evaluation harness for Agent 2's community partner extraction. It scores against a hand-labeled gold set and reports precision, recall, and F1 with a Wilson score confidence interval, which behaves better than a normal approximation on a set this small. For the LLM path specifically, it also runs each example multiple times to check self-consistency: temperature 0 doesn't guarantee identical output on every call, and for a funder-facing report, knowing whether the same input can produce a different partner list on a rerun matters as much as knowing whether it got the right answer once.

Running it against the regex fallback (the path that needs no API key and is also what production falls back to if the live call ever fails) surfaced two real bugs I'd missed the first time around:

- The name-capture regex ran all the way to the next comma, so "partnered with the Riverside Food Bank to set up a composting program" was extracting the entire clause as the partner's name instead of stopping at "Riverside Food Bank."
- The NGO keyword list didn't actually include the word "NGO," so an organization literally named "GreenFuture NGO" got default-classified as "community."

Both are fixed now. Precision on the gold set went from 0 to 0.5 and recall from 0 to 0.3 (F1 0.375, 95% CI on precision [0.19, 0.81] given the small n). That's still an honest, imperfect number, not a victory lap: the fallback still misses partners mentioned without one of its trigger phrases ("the mayor's office sent a representative" isn't caught, since nothing there says "partnered with" or "worked with"), and it still sometimes over-merges multi-word partner names joined by "and" by design, to avoid incorrectly splitting names like "Boys and Girls Club." The harness's job is to make those limitations visible and measurable, not to make them disappear. The LLM path is the primary path for exactly this reason, and evaluating that one for real (accuracy plus self-consistency across repeated calls) needs live Azure credentials this environment doesn't have, so `--mode llm` is written and ready but hasn't been run against production numbers yet.

## Tech stack

Python, Streamlit, LangChain and LangGraph, Azure OpenAI (GPT-4.1, `text-embedding-3-large`), Azure AI Foundry, FAISS, SQLite for the POC with Azure planned for production.

## Status

Proof of concept, demoed to program staff. Production deployment is planned on the organization's own Azure infrastructure.

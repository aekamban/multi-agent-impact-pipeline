# TCImpact Project Briefing 

---

I am building a Streamlit app called TCImpact for The Climate Initiative (TCI),
an international environmental education nonprofit (theclimateinitiative.org).
The app has four AI agents orchestrated by LangChain on Azure OpenAI GPT-4.1.

## BACKGROUND

TCI trains 5,500+ educators across 50 countries who run "Learning Labs"
(climate education units) with 570,000+ students, 30,000 of whom complete
Action Projects. TCI currently collects data via a year-end Jotform and lacks
the outcome measurement data required by major funders (EPA grants, Bloomberg
Philanthropies, Bezos Earth Fund, education-sector evidence-tier funders).

TCI recently received Moore Foundation funding to build a better action project
map. Our app must output data that feeds that map backend directly.

TCI's Director of Operations (Kate Keefer) has confirmed there is no
formalized measurement framework yet — this tool will help establish it.

## THE THREE CORE VALUE PROPOSITIONS

1. CURRICULUM INTEGRATION ASSISTANT
   The single biggest barrier to teacher adoption is that teachers cannot see
   how to fit a learning lab into their existing curriculum without rewriting
   it. The app replicates the support TCI's Executive Director provides at the
   annual educators retreat — helping teachers find NGSS/curriculum alignment
   connections so the learning lab becomes academically justifiable in their
   subject area. This is the highest-leverage driver of teacher adoption.

2. SOCRATIC STUDENT COACH
   When student groups have ideas that are too ambitious or lack academic
   rigor, the app guides them using Socratic questioning — not by telling
   them what to do, but by asking questions that help them discover how to
   improve their own project. This matches TCI's empowerment philosophy.
   The app never tells a student their idea is bad. It asks questions like:
   "What would happen if you reached 10 times as many people?" or "What
   would your school principal need to see before approving this?"

3. JOTFORM DRAFT GENERATOR + DEADLINE NUDGE
   Teachers delay Jotform submission because they are overwhelmed at
   year-end, cannot find materials, and do not know what a strong submission
   looks like. The app collects materials passively throughout the year,
   knows the Jotform fields, and auto-drafts the submission. A nudge system
   tied to TCI's actual submission deadline doubles submission rates.

## THE THREE PHASES

PHASE 1 — PLANNING (teacher + students)
  Teacher: curriculum alignment support, lab selection, group setup,
           classroom code generation, previews what strong projects look like,
           pre-survey (confidence + preparedness baseline)
  Student: project idea exploration, feasibility check via Socratic
           questioning, initial impact estimate, planning doc started

PHASE 2 — IMPLEMENTATION (teacher + students, records mutable throughout)
  Teacher: safety guidance for field trips, admin communication templates,
           group dynamics support, milestone check-ins, materials collection
  Student: blocker resolution (admin permission, logistics, unexpected issues),
           carbon/community impact calculations with math support,
           encouragement for students who want to give up on calculations

PHASE 3 — ANALYSIS & REPORTING (teacher + students)
  Teacher: aggregates group impacts, Jotform draft auto-generated,
           deadline reminder system, post-survey, funder-ready summary
  Student: understands their project's impact, sees how to grow it over time,
           community leadership pathway surfaced

## TWO USER TYPES

1. TEACHERS — access via link shared in learning lab materials or retreat demo.
   Use app across all three phases. Pre/post survey captures outcome data.
   Classroom code links their students to their session anonymously.

2. STUDENTS — access via QR code on teacher's slide OR shareable link
   (important: many US public schools ban phones; students need
   Chromebook-compatible browser link as primary access method).
   Students are fully anonymous in the database.

## KEY PEDAGOGICAL PRINCIPLES (from TCI + teacher experience)

- EMPOWERMENT over instruction: app asks questions, doesn't give answers
- NGSS alignment framing: real-world contexts fit into any curriculum
- MATH SUPPORT for En-ROADS: many students abandon carbon calculations
  due to math anxiety; app provides step-by-step scaffolding
- PIVOT SUPPORT: projects change direction mid-implementation; this is
  normal and valuable; app helps groups pivot without demoralizing them
- MULTIPLE LABS PER TEACHER: teachers often run 2-3 labs per year;
  app handles multiple active sessions simultaneously

## REAL DATA CHARACTERISTICS (from 46 actual Jotform submissions)

Lab usage frequency in real data:
  17x Agriculture and Climate Change  [Track B]  ← most popular
  12x Civics Climate Action           [Track B]
  10x Climate Justice and Equity      [Track B]
   7x Renewable Energy                [Track B]
   4x Climate Impacts with En-ROADS   [Track A]  ← only carbon target lab
   4x Wildfires                       [Track B]
   3x Floods and Droughts             [Track B]
   3x Sea Level Rise                  [Track B]

CRITICAL: Track B projects (awareness/community/policy) are the majority
by a wide margin. The funder story must lead with Track B impact, not
carbon calculations. En-ROADS is 4/46 submissions (9%).

Lab names in submissions are informal and varied — Agent 2 uses fuzzy
matching against a lab_name_aliases table seeded from real data.

Student count field is often qualitative (e.g. "10-25, K-8th", "500+") —
Agent 2 normalizes to min/max integers and preserves original display value.

## TECH STACK

- Python, Streamlit, LangChain (langchain-classic for AgentExecutor)
- Azure OpenAI GPT-4.1 (chat), Azure text-embedding-3-large (RAG)
- Azure AI Foundry hub: tcimpact-hub-ak (East US)
- FAISS vector store for RAG over 11 learning lab documents
- SQLite for anonymized storage (local POC, Azure production)
- Deployed locally for POC, transfer to TCI Azure credentials for production

## THE FOUR AGENTS

### Agent 1 — Learning Lab Expert + Curriculum Integration Assistant
- RAG over all 11 TCI learning lab .txt files
- Teacher mode: curriculum alignment support — given teacher's subject,
  grade level, and standards (e.g. NGSS chemistry), suggests how to weave
  the learning lab into existing curriculum without rewriting it
- Student mode: answers questions about lab content, guides project
  ideation using Socratic questioning, three lenses framework
  (sociocultural, economic, ecological)
- Math support mode: step-by-step scaffolding for En-ROADS carbon
  calculations, designed for students with math anxiety
- Safety guardrails: high school appropriate, never gives direct
  answers when Socratic guidance is better, never gives medical/legal/
  administrative advice (e.g. "consult your school administrator")

### Agent 2 — Intake & Structuring Agent
- Processes teacher and student input across all three phases
- Fuzzy-matches informal lab names to canonical names via alias table
- Normalizes messy student count fields ("10-25, K-8th" → min:10, max:25)
- Assigns Track A (En-ROADS) or Track B (all other labs)
- Extracts community partnerships from narrative text as structured JSON
- Applies 5-dimension rubric scoring (reach, depth, equity,
  sustainability, fidelity) — handles minimal submissions gracefully
  without penalizing brevity unfairly
- Captures disaggregation fields: locale, school type, country, grade band
- Records are NEVER locked — mutable throughout all phases

### Agent 3 — Impact Calculator
- Track A: CO2 reduction using EPA emissions factors, transparent
  assumptions, step-by-step math shown (supports students with math
  anxiety), progress toward 10,000 lb target
- Track B: reach, behavior change proxy, awareness scale,
  community partnerships count, policy outcomes as funder metrics
- Always shows methodology — explainability is non-negotiable for
  both funders and for students learning the math

### Agent 4 — Community Impact & Funder Summary
- Scores community impact on 4 dimensions (reach, depth, equity,
  sustainability)
- Identifies carbon vs. community tradeoff narrative
- Generates EPA logic-model-structured grant-ready summary:
  INPUTS → ACTIVITIES → OUTPUTS → SHORT-TERM OUTCOMES →
  INTERMEDIATE OUTCOMES → EQUITY NOTE
- Auto-drafts Jotform submission text mapped to actual Jotform fields
- Generates Moore Foundation map-ready JSON export per project
- Powers password-protected funder dashboard

## DATA SCHEMA (SQLite — key tables)

sessions          — core unit: one teacher + one lab + one academic year
                    classroom_code links students anonymously
                    status: planning → implementing → analyzing → complete
                    ALL fields mutable throughout (updated_at tracks history)
                    jotform_draft_text: AI-generated, teacher can edit

student_groups    — anonymous groups within a session
                    ability_level, has_field_trip_access, special_interests
                    informs Agent 1 Socratic coaching approach

projects          — one per student group
                    num_students_min/max (normalized from messy input)
                    community_partnerships_json (extracted by Agent 2)
                    map_export_json (Moore Foundation format)
                    media_urls, student_quotes, highlights

teachers          — hashed name + email for privacy
                    school_type (public/private/charter/montessori/
                    tribal_school/community_org)
                    city + state_province + country (for map)
                    subject_area, curriculum_standards

pre_post_surveys  — pre: captures confidence, preparedness, local context,
                    available resources (feeds Agent 1 planning support)
                    post: captures delta, student engagement, NPS proxy

learning_labs     — 11 canonical labs with usage_count from real data
lab_name_aliases  — fuzzy matching table seeded from real submissions
impact_summaries  — aggregated metrics for funder dashboard + map export

## JOTFORM FIELDS (exact — for Jotform draft generation)

Col 1:  Submission Date
Col 2:  Name
Col 3:  Email
Col 4:  Phone Number
Col 5:  Name of your school or institution
Col 6:  How many students completed your Action Project?
Col 7:  Which Learning Lab(s) did you use?
Col 8:  Which best captures your project's thematic topic?
Col 9:  Please give an overview of your project
Col 12: Please provide any highlights or student feedback
Col 15: Please upload any supporting documents or evidence
Col 16: Would you like to be considered for TCI merchandise?
Col 17: Mailing address
Col 18: Agreement to TCI use of materials

## ADDITIONAL FEATURES

Classroom Code System:
  Format: TCI-XXXX (4 alphanumeric characters)
  Links student activity to teacher session anonymously
  Displayed as QR code + plain text link for Chromebook access
  Students never enter personal information

Jotform Deadline Nudge:
  Teacher sets or confirms submission deadline in app
  App sends in-app reminders at 2 weeks, 1 week, 3 days before deadline
  Draft is always pre-populated so teacher just needs to review + submit

Materials Collection (passive throughout year):
  App prompts teacher at natural moments: "Do you have any photos
  from today's field trip you'd like to add?" rather than asking
  for everything at once at year-end

Map Export (Moore Foundation integration):
  JSON per project: {lat, lng, school_name, lab_name, project_type,
  grade_band, num_students, duration_weeks, thematic_topic,
  community_partnerships_count, submission_date}
  Bulk export from funder dashboard for TCI map team

Educator Retreat Demo:
  Abi to attend annual TCI educators retreat to demo app
  App includes a "curriculum alignment" flow specifically designed
  to replicate the support TCI's ED provides at retreats



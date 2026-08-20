# tcimpact-poc
Proof of concept impact measurement app for The Climate Initiative

## Stack

- Python
- Streamlit
- LangChain
- Azure OpenAI GPT-4.1
- Azure text-embedding-3-large
- FAISS
- SQLite

## Local setup

1. Clone the repo

2. Create a virtual environment

   python -m venv .venv

3. Activate it

   Windows:
   .venv\Scripts\activate

   Mac/Linux:
   source .venv/bin/activate

4. Install dependencies

   pip install -r requirements.txt

5. Copy the environment template

   cp .env.example .env

6. Add the required Azure OpenAI credentials to `.env`.

7. [ADD ANY DATABASE / RAG INITIALIZATION COMMAND HERE]

8. Start the app

   streamlit run [YOUR_MAIN_APP_FILE].py

## Suggested prototype test

1. Open the app as a teacher.
2. Select [example Learning Lab].
3. Test the curriculum-alignment workflow.
4. Create a classroom/session.
5. Enter the student experience and test Socratic project coaching.
6. Test the impact/reporting workflow.

## Architecture

TCImpact has four agents:

1. Learning Lab Expert / Curriculum Integration
2. Intake & Structuring
3. Impact Calculator
4. Community Impact & Funder Summary

See `BRIEFING.md` for detailed product and architecture context.

## Notes

This is a proof of concept, not a production deployment.

Please don't commit credentials or real student/teacher PII.

# ContextIQ — Sales Meeting Contextualizer

A focused Streamlit prototype that turns prospect interaction history into a pre-meeting brief.

## Features
- Ingest meeting transcripts or summaries, linked to a unique prospect ID.
- Store each interaction in a dedicated Hindsight memory bank.
- Retrieve relevant memories before a meeting.
- Use Groq to produce an evidence-based brief: objectives, commitments, objections, stakeholders, agenda and questions.
- Refresh a concise account snapshot after every interaction.
- Visible chronological timeline and downloadable Markdown brief.
- Fictional three-meeting demo story spanning two weeks.

## 1. Requirements
- Python 3.10+
- Hindsight API key (optional for local-only demo; required for Hindsight memory)
- Groq API key (optional for AI synthesis; required for AI briefs and evolving snapshot)

## 2. Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and add your keys:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
HINDSIGHT_API_KEY=your_hindsight_api_key
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
```

If you use a self-hosted Hindsight deployment, set `HINDSIGHT_BASE_URL` to its API URL.

## 3. Run

```bash
streamlit run app.py
```

Click **Load 3-meeting demo** in the sidebar. Then open **Meeting brief**, enter a goal, and generate the brief. The fictional account is Acme Industries.

## 4. Demo narrative (60 seconds)
1. **Before memory:** Use an empty prospect account. The app has no history to brief from.
2. **Learning:** Click Load 3-meeting demo. The timeline shows discovery (two weeks ago), follow-up (one week ago), and solution review (today).
3. **Expert:** Generate the brief. With Groq + Hindsight configured, it should connect the original pricing objection to the ROI model and phased rollout, while surfacing the pilot and security-pack commitments.

## Architecture
- **Streamlit:** UI and workflow.
- **SQLite:** local audit/timeline and evolving snapshot display.
- **Hindsight:** durable, prospect-isolated memory banks; `retain` on ingestion and `recall` before briefing.
- **Groq:** account snapshot update after each interaction and final briefing synthesis.

## Important implementation notes
- A stable bank ID is derived from each prospect ID, so recall is isolated per prospect.
- Raw meeting summaries are stored locally for a visible chronological timeline and are also retained in Hindsight when configured.
- The app refreshes the account snapshot from the full chronological local history after every meeting. The snapshot is displayed in the Memory timeline tab.
- In local demo mode, records persist in `sales_context.db`; no Hindsight or Groq calls are made.
- Hindsight SDK usage follows the official Python SDK: `create_bank`, `retain`, `recall`. Groq uses chat completions.

## Security
- Never commit `.env`, API keys, or real customer transcripts.
- Use fictional data for hackathon demos.
- Add authentication, role-based access, encryption, retention controls, and audit logging before production use.

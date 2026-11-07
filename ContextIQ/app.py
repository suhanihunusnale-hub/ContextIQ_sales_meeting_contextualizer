import os
import json
import sqlite3
import hashlib
from datetime import datetime, date, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
DB_PATH = Path("sales_context.db")
HINDSIGHT_URL = os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io")
HINDSIGHT_KEY = os.getenv("HINDSIGHT_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

st.set_page_config(page_title="ContextIQ | Sales Briefing", page_icon="🧭", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #f5f7fb; }
.block-container { padding-top: 1.6rem; max-width: 1240px; }
.hero { background: linear-gradient(115deg,#101d3a,#1d3764 65%,#315d83); padding: 27px 32px; border-radius: 20px; color: white; margin-bottom: 22px; }
.hero h1 { font-family: Manrope,sans-serif; font-size: 31px; margin: 0 0 5px 0; color: white; }
.hero p { color: #d7e4f4; margin: 0; font-size: 14px; }
.eyebrow { color:#9cc7f4; text-transform:uppercase; letter-spacing:2px; font-size:10px; font-weight:700; }
.panel { background:white; border:1px solid #e6eaf1; border-radius:16px; padding:18px 20px; }
.metric { background:white; border:1px solid #e6eaf1; border-radius:14px; padding:15px 17px; }
.metric .k { color:#6b7890; font-size:12px; }
.metric .v { color:#172743; font-family:Manrope,sans-serif; font-size:25px; font-weight:800; }
.pill { display:inline-block; background:#eaf3ff; color:#245b94; border-radius:20px; padding:4px 10px; font-size:11px; font-weight:700; }
.smallmuted { color:#7b879a; font-size:12px; }
div[data-testid="stTabs"] button { font-weight:600; }
.stButton>button[kind="primary"] { background:#1e4778; border:0; border-radius:10px; }
</style>
""", unsafe_allow_html=True)

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, prospect_id TEXT, prospect_name TEXT,
        company TEXT, meeting_date TEXT, meeting_type TEXT, summary TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS profiles (
        prospect_id TEXT PRIMARY KEY, snapshot TEXT, updated_at TEXT)""")
    conn.commit()
    return conn

conn = db()

def bank_id_for(prospect_id):
    safe = "".join(c.lower() if c.isalnum() else "-" for c in prospect_id).strip("-")
    suffix = hashlib.sha1(prospect_id.encode()).hexdigest()[:6]
    return f"prospect-{safe[:32]}-{suffix}"

def hindsight_client():
    if not HINDSIGHT_KEY:
        return None
    from hindsight_client import Hindsight
    return Hindsight(base_url=HINDSIGHT_URL, api_key=HINDSIGHT_KEY)

def ensure_bank(client, prospect_id, prospect_name, company):
    bid = bank_id_for(prospect_id)
    try:
        client.create_bank(
            bank_id=bid,
            name=f"{prospect_name} | {company}",
            background="Sales account memory. Store only interactions for this prospect. Preserve chronology, objections, commitments, stakeholder context and outcomes."
        )
    except Exception:
        # Existing bank is expected on subsequent meetings; retain/recall will verify access.
        pass
    return bid

def groq_client():
    if not GROQ_KEY:
        return None
    from groq import Groq
    return Groq(api_key=GROQ_KEY)

def groq_text(system, user, temperature=0.2):
    client = groq_client()
    if not client:
        return None
    out = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=temperature,
        messages=[{"role":"system","content":system},{"role":"user","content":user}]
    )
    return out.choices[0].message.content

def local_meetings(prospect_id):
    return conn.execute("SELECT * FROM meetings WHERE prospect_id=? ORDER BY meeting_date, id", (prospect_id,)).fetchall()

def local_snapshot(prospect_id):
    row = conn.execute("SELECT snapshot FROM profiles WHERE prospect_id=?", (prospect_id,)).fetchone()
    return row["snapshot"] if row else ""

def add_meeting(prospect_id, prospect_name, company, meeting_date, meeting_type, summary):
    conn.execute(
        "INSERT INTO meetings(prospect_id,prospect_name,company,meeting_date,meeting_type,summary) VALUES(?,?,?,?,?,?)",
        (prospect_id, prospect_name, company, str(meeting_date), meeting_type, summary)
    )
    conn.commit()

def update_profile(prospect_id, prospect_name, company):
    meetings = local_meetings(prospect_id)
    history = "\n\n".join(
        f"{m['meeting_date']} | {m['meeting_type']}\n{m['summary']}" for m in meetings
    )
    prompt = f"""Create a compact, continuously updated account memory for a sales executive.
Separate confirmed facts from assumptions. Track: business goals, stakeholders and roles,
pain points, objections and whether/how they were resolved, product interests, decisions,
promises made by either side, deadlines, and next steps. Keep unresolved commitments visible.
Do not invent facts. Return concise bullets and preserve dates.

Prospect: {prospect_name} at {company}
Interaction history:
{history}"""
    snapshot = groq_text("You are a meticulous sales operations analyst. Never fabricate.", prompt)
    if not snapshot:
        snapshot = "Account history updated locally. Add a Groq API key to generate an AI-maintained account snapshot."
    conn.execute(
        "INSERT INTO profiles(prospect_id,snapshot,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(prospect_id) DO UPDATE SET snapshot=excluded.snapshot, updated_at=excluded.updated_at",
        (prospect_id, snapshot, datetime.now().isoformat(timespec="minutes"))
    )
    conn.commit()
    return snapshot

def retrieve_hindsight(prospect_id, query):
    client = hindsight_client()
    if not client:
        return [], "Local demo mode — Hindsight is not connected."
    bid = bank_id_for(prospect_id)
    try:
        result = client.recall(bank_id=bid, query=query, max_tokens=5000, budget="mid")
        memories = [getattr(x, "text", str(x)) for x in (result.results or [])]
        return memories, "Hindsight memory retrieved"
    finally:
        client.close()

def save_to_hindsight(prospect_id, prospect_name, company, meeting_date, meeting_type, summary):
    client = hindsight_client()
    if not client:
        return False, "Saved to local demo history. Add HINDSIGHT_API_KEY to sync memory."
    try:
        bid = ensure_bank(client, prospect_id, prospect_name, company)
        content = (
            f"Prospect ID: {prospect_id}\nProspect: {prospect_name}\nCompany: {company}\n"
            f"Meeting date: {meeting_date}\nMeeting type: {meeting_type}\n"
            f"Interaction summary:\n{summary}"
        )
        client.retain(
            bank_id=bid,
            content=content,
            context=f"Sales meeting interaction with {prospect_name} at {company}",
            metadata={"prospect_id": prospect_id, "meeting_date": str(meeting_date), "meeting_type": meeting_type}
        )
        return True, "Meeting stored in Hindsight memory."
    finally:
        client.close()

def make_brief(prospect_id, prospect_name, company, meeting_goal, memories):
    meetings = local_meetings(prospect_id)
    local_history = "\n\n".join(
        f"{m['meeting_date']} | {m['meeting_type']}\n{m['summary']}" for m in meetings
    )
    memory_context = "\n".join(memories) if memories else "No Hindsight memories returned."
    prompt = f"""Prepare a practical pre-meeting brief for an Account Executive.
Use only evidence below. Clearly label unknowns; never make up commitments or dates.
Include:
1. Meeting objective (tailored to the stated goal)
2. Prospect context and what matters to them
3. Outstanding commitments (owner, action, due date if known)
4. Objections / risks and how the conversation evolved
5. Stakeholders and influence
6. Suggested agenda and 3 sharp questions
7. Opening line that demonstrates continuity.
For every important insight, cite the interaction date in square brackets. If dates are missing, say date not recorded.

Prospect: {prospect_name}, {company}
Next meeting goal: {meeting_goal}
Hindsight retrieved memories:
{memory_context}
Local chronological interaction log:
{local_history}
Current account snapshot:
{local_snapshot(prospect_id)}"""
    answer = groq_text(
        "You are an elite enterprise sales coach. Be concise, specific, evidence-based and useful. "
        "Do not present guesses as facts. Prefer dated evidence.",
        prompt
    )
    if answer:
        return answer
    # Useful local-only fallback for the app to work before API keys are configured.
    if not meetings:
        return "No meeting history found yet. Add an interaction first, then generate a brief."
    recent = meetings[-3:]
    lines = [
        f"### Meeting objective\n{meeting_goal or 'Re-establish context and agree on a concrete next step.'}",
        "### Recent interaction history"
    ]
    for m in recent:
        lines.append(f"- **{m['meeting_date']} · {m['meeting_type']}** — {m['summary']}")
    lines += [
        "### Outstanding commitments / objections\nReview the notes above and confirm owners and due dates before the call.",
        "### Suggested opening\n“Thanks for making time again. I’d like to pick up where we left off and confirm the best next step.”",
        "\n*Local-only fallback: connect Groq for a synthesized, structured briefing.*"
    ]
    return "\n\n".join(lines)

def seed_demo():
    prospect_id = "acme-industries"
    demo = [
        (date.today()-timedelta(days=14), "Discovery", "Client: Acme Industries. Main concern is total cost and proving ROI before committing. VP Operations Priya Sharma is the decision maker; IT lead Daniel Lee will evaluate technical fit. They currently use spreadsheets and a legacy inventory tool. Asked for a clear implementation timeline and pricing breakdown."),
        (date.today()-timedelta(days=7), "Product follow-up", "Client liked the ERP and Slack integrations and said reducing duplicate data entry would help the operations team. Pricing remains the biggest concern. AE promised a transparent tier comparison and a 90-day ROI model by Friday. Daniel requested SSO and role-based access details."),
        (date.today(), "Solution review", "Presented the tier comparison and 90-day ROI model. Priya said the phased rollout makes the investment easier to justify and asked for a pilot proposal for 25 users. Daniel confirmed the integrations meet their requirements, but wants security documentation. AE committed to send pilot scope and security pack by Wednesday. Budget approval still pending with Finance.")
    ]
    for d, typ, summary in demo:
        add_meeting(prospect_id, "Acme Industries", "Acme Industries", d, typ, summary)
        save_to_hindsight(prospect_id, "Acme Industries", "Acme Industries", d, typ, summary)
    update_profile(prospect_id, "Acme Industries", "Acme Industries")
    return prospect_id

# Header
st.markdown("""
<div class="hero">
  <div class="eyebrow">ContextIQ · Sales intelligence</div>
  <h1>Walk into every meeting already knowing the story.</h1>
  <p>A living memory of every prospect conversation — objections, promises, stakeholders and what changed.</p>
</div>
""", unsafe_allow_html=True)

prospects = conn.execute("SELECT prospect_id, MAX(prospect_name) name, MAX(company) company, COUNT(*) n, MAX(meeting_date) last_date FROM meetings GROUP BY prospect_id ORDER BY last_date DESC").fetchall()
prospect_options = {f"{p['name']} · {p['company']}": p['prospect_id'] for p in prospects}

with st.sidebar:
    st.markdown("### 🧭 ContextIQ")
    st.caption("Your prospect memory workspace")
    st.markdown("---")
    st.markdown("**Connection status**")
    st.write("🟢 Groq connected" if GROQ_KEY else "🟡 Groq not configured")
    st.write("🟢 Hindsight connected" if HINDSIGHT_KEY else "🟡 Hindsight local-demo mode")
    st.caption("Keys stay in your local .env file.")
    st.markdown("---")
    if st.button("✨ Load 3-meeting demo", use_container_width=True):
        pid = seed_demo()
        st.session_state["selected_pid"] = pid
        st.success("Demo account loaded.")
        st.rerun()
    st.caption("Creates a fictional Acme Industries account with a two-week conversation arc.")

tab_brief, tab_ingest, tab_history = st.tabs(["📋 Meeting brief", "➕ Add interaction", "🧠 Memory timeline"])

with tab_brief:
    left, right = st.columns([1.1, 2.1], gap="large")
    with left:
        st.markdown("#### Choose a prospect")
        if prospect_options:
            labels = list(prospect_options.keys())
            default_idx = 0
            selected_pid = st.session_state.get("selected_pid")
            if selected_pid in prospect_options.values():
                default_idx = list(prospect_options.values()).index(selected_pid)
            chosen = st.selectbox("Account", labels, index=default_idx, label_visibility="collapsed")
            pid = prospect_options[chosen]
            p = conn.execute("SELECT prospect_name,company FROM meetings WHERE prospect_id=? LIMIT 1", (pid,)).fetchone()
            st.markdown(f"<div class='panel'><span class='pill'>ACCOUNT MEMORY</span><h3>{p['prospect_name']}</h3><div class='smallmuted'>{p['company']}</div><br/>", unsafe_allow_html=True)
            rows = local_meetings(pid)
            a,b = st.columns(2)
            a.metric("Interactions", len(rows))
            b.metric("Last touch", rows[-1]["meeting_date"] if rows else "—")
            st.markdown("</div>", unsafe_allow_html=True)
            goal = st.text_area("What is the goal of the next meeting?", placeholder="e.g. Secure agreement on a 25-user pilot and confirm the Finance approval path.", height=100)
            if st.button("Generate meeting brief", type="primary", use_container_width=True):
                with st.spinner("Recalling account history and preparing your brief..."):
                    memories, status = retrieve_hindsight(pid, f"Chronological sales history for {p['prospect_name']}: objections, commitments, stakeholders, decisions, and changes over time.")
                    brief = make_brief(pid, p["prospect_name"], p["company"], goal, memories)
                    st.session_state["brief"] = brief
                    st.session_state["brief_status"] = status
                    st.session_state["brief_pid"] = pid
        else:
            st.info("No accounts yet. Load the demo or add your first interaction.")
            pid = None
    with right:
        st.markdown("#### Your pre-meeting briefing")
        if st.session_state.get("brief") and st.session_state.get("brief_pid") == pid:
            st.markdown("<div class='panel'>", unsafe_allow_html=True)
            st.markdown(st.session_state["brief"])
            st.markdown("</div>", unsafe_allow_html=True)
            st.caption(st.session_state.get("brief_status", ""))
            st.download_button("Download brief", st.session_state["brief"], file_name="meeting_brief.md", mime="text/markdown")
        else:
            st.markdown("""
            <div class="panel">
            <div class="eyebrow" style="color:#6484aa">YOUR NEXT MEETING, DE-RISKED</div>
            <h3 style="color:#172743">The context your CRM notes don't give you.</h3>
            <p style="color:#68778e">Select an account, add the meeting goal, and generate a brief grounded in the full interaction history.</p>
            <hr/>
            <p>◉ <b>Objectives</b> — what this meeting needs to achieve</p>
            <p>◉ <b>Commitments</b> — what you promised and what they owe you</p>
            <p>◉ <b>Objections</b> — concerns raised and how they evolved</p>
            <p>◉ <b>Stakeholders</b> — who cares about what</p>
            <p>◉ <b>Suggested questions</b> — move the deal forward</p>
            </div>
            """, unsafe_allow_html=True)

with tab_ingest:
    st.markdown("#### Capture what happened")
    st.caption("Paste a transcript, call summary, or concise notes. Each interaction is stored against a stable prospect ID.")
    c1,c2 = st.columns(2)
    with c1:
        prospect_name = st.text_input("Prospect name", placeholder="e.g. Acme Industries")
        company = st.text_input("Company", placeholder="e.g. Acme Industries")
        prospect_id = st.text_input("Unique prospect ID", placeholder="e.g. acme-industries")
    with c2:
        meeting_date = st.date_input("Meeting date", value=date.today())
        meeting_type = st.selectbox("Interaction type", ["Discovery", "Demo", "Product follow-up", "Negotiation", "Email follow-up", "Other"])
    summary = st.text_area("Meeting transcript / summary", height=220, placeholder="What did the prospect say? Capture objections, decisions, stakeholders, commitments, dates, product interests and next steps...")
    if st.button("Store interaction & update account memory", type="primary"):
        if not prospect_name.strip() or not company.strip() or not prospect_id.strip() or not summary.strip():
            st.error("Please fill in the prospect, company, unique ID and interaction summary.")
        else:
            with st.spinner("Storing interaction and updating the account snapshot..."):
                add_meeting(prospect_id.strip(), prospect_name.strip(), company.strip(), meeting_date, meeting_type, summary.strip())
                ok, message = save_to_hindsight(prospect_id.strip(), prospect_name.strip(), company.strip(), meeting_date, meeting_type, summary.strip())
                snapshot = update_profile(prospect_id.strip(), prospect_name.strip(), company.strip())
            st.success(message)
            st.info("Account snapshot refreshed." if GROQ_KEY else "Interaction saved. Add GROQ_API_KEY to generate the evolving AI account snapshot.")
            st.session_state["selected_pid"] = prospect_id.strip()

with tab_history:
    st.markdown("#### The memory is visible")
    st.caption("Chronological evidence is shown beside the evolving account snapshot.")
    if prospect_options:
        chosen_hist = st.selectbox("Choose account timeline", list(prospect_options.keys()), key="history_account")
        hpid = prospect_options[chosen_hist]
        history = local_meetings(hpid)
        snap = local_snapshot(hpid)
        col_a,col_b = st.columns([1.25,1], gap="large")
        with col_a:
            st.markdown("**Interaction timeline**")
            for i,m in enumerate(history):
                st.markdown(f"""
                <div class="panel" style="margin-bottom:10px">
                  <span class="pill">MEETING {i+1}</span>
                  <b style="color:#172743"> · {m['meeting_type']}</b>
                  <div class="smallmuted">{m['meeting_date']}</div>
                  <p style="color:#45536a;margin-bottom:0">{m['summary']}</p>
                </div>""", unsafe_allow_html=True)
        with col_b:
            st.markdown("**Evolving account snapshot**")
            if snap:
                st.markdown(f"<div class='panel'>{snap.replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
            else:
                st.info("Add an interaction to create the first account snapshot.")
    else:
        st.info("Load the demo or add an interaction to see the memory timeline.")

st.markdown("---")
st.caption("ContextIQ prototype · Use fictional or approved business data during demos. Do not paste confidential customer information into an unapproved environment.")

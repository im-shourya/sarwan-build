import json

import streamlit as st
from pypdf import PdfReader

import fallback
import prompts
from sarvam_client import CHAT_MODEL, ask, chat, parse_json

st.set_page_config(page_title="PrepPilot", page_icon="🎯", layout="wide")

state = st.session_state
state.setdefault("profile", None)
state.setdefault("resume", None)
state.setdefault("roadmap", None)
state.setdefault("interview", [])

CATEGORY_COLORS = {"DSA": "blue", "OS": "green", "System Design": "violet"}


def profile_json():
    return json.dumps(state.profile or {}, indent=2)


def resume_json():
    return json.dumps(state.resume or {}, indent=2)


def all_topics():
    if not state.roadmap:
        return []
    return [(w["weekNumber"], t) for w in state.roadmap["weeks"] for t in w["topics"]]


# ---------- Onboarding ----------
def onboarding_page():
    st.header("1 · Tell us about you")
    profile = state.profile or {}
    with st.form("onboarding"):
        role = st.text_input("Target role", profile.get("targetRole", "SDE Intern"))
        companies = st.text_input(
            "Target companies (comma separated)", ", ".join(profile.get("targetCompanies", ["Google", "Flipkart"]))
        )
        col1, col2 = st.columns(2)
        college = col1.text_input("College", profile.get("college", ""))
        year = col2.selectbox("Year", ["1st", "2nd", "3rd", "4th", "Graduated"], index=2)
        level = st.select_slider(
            "Comfort level", ["Beginner", "Intermediate", "Advanced"], value=profile.get("comfortLevel", "Intermediate")
        )
        resume_file = st.file_uploader("Resume (PDF)", type=["pdf"])
        submitted = st.form_submit_button("Save profile", type="primary")

    if submitted:
        state.profile = {
            "targetRole": role,
            "targetCompanies": [c.strip() for c in companies.split(",") if c.strip()],
            "college": college,
            "year": year,
            "comfortLevel": level,
        }
        if resume_file:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(resume_file).pages)
            if text.strip():
                with st.spinner("Reading your resume with Sarvam-105B…"):
                    try:
                        state.resume = parse_json(ask(prompts.RESUME_EXTRACTION.format(resume_text=text[:12000])))
                    except Exception as e:
                        st.error(f"Resume extraction failed: {e}")
            else:
                st.warning("No text found in that PDF (is it a scanned image?).")
        st.success("Profile saved. Head to **Roadmap** next.")

    if state.resume:
        r = state.resume
        st.subheader(f"Resume: {r.get('name', '')}")
        st.write("**Skills:** " + ", ".join(r.get("skills", [])))
        for p in r.get("projects", []):
            st.markdown(f"- **{p['name']}** — {p['description']} _({', '.join(p.get('techStack', []))})_")


# ---------- Roadmap ----------
def roadmap_page():
    st.header("2 · Your 4-week roadmap")
    if not state.profile:
        st.info("Fill in onboarding first.")
        return

    col1, col2 = st.columns([1, 4])
    if col1.button("Generate roadmap", type="primary"):
        with st.spinner("Sarvam-105B is planning your prep…"):
            try:
                state.roadmap = parse_json(
                    ask(prompts.ROADMAP.format(profile_json=profile_json(), resume_json=resume_json()))
                )
            except Exception as e:
                st.warning(f"Live generation failed ({e}); showing a default roadmap.")
                state.roadmap = fallback.ROADMAP
    if col2.button("Use default roadmap"):
        state.roadmap = fallback.ROADMAP

    if not state.roadmap:
        return

    cols = st.columns(len(state.roadmap["weeks"]))
    for col, week in zip(cols, state.roadmap["weeks"]):
        with col.container(border=True):
            st.markdown(f"#### Week {week['weekNumber']}")
            st.caption(week["focus"])
            for t in week["topics"]:
                color = CATEGORY_COLORS.get(t["category"], "gray")
                st.markdown(f":{color}-badge[{t['category']}] **{t['name']}**")
                st.caption(t["why"])
            st.markdown("**Daily challenges**")
            for c in week.get("dailyChallenges", []):
                st.markdown(f"- {c}")


# ---------- Practice ----------
def practice_page():
    st.header("3 · Practice")
    topics = all_topics()
    tab_topic, tab_review = st.tabs(["Topic breakdown", "Code review"])

    with tab_topic:
        if not topics:
            st.info("Generate a roadmap first.")
        else:
            labels = [f"Week {w} · {t['name']} ({t['category']})" for w, t in topics]
            idx = st.selectbox("Topic", range(len(labels)), format_func=lambda i: labels[i])
            state.current_topic = topics[idx][1]["name"]
            if st.button("Explain + give me questions", type="primary"):
                t = topics[idx][1]
                p = state.profile
                with st.spinner("Generating…"):
                    st.markdown(
                        ask(
                            prompts.TOPIC_PRACTICE.format(
                                target_role=p["targetRole"],
                                companies=", ".join(p["targetCompanies"]) or "top tech companies",
                                level=p["comfortLevel"],
                                topic=t["name"],
                                category=t["category"],
                            )
                        )
                    )

    with tab_review:
        problem = st.text_area("Problem statement", "Given an array of integers and a target, return indices of two numbers that add up to target.")
        code = st.text_area(
            "Your solution",
            "def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] + nums[j] == target:\n                return [i, j]",
            height=220,
        )
        if st.button("Review my code", type="primary"):
            with st.spinner("Reviewing…"):
                st.markdown(ask(prompts.CODE_REVIEW.format(problem_statement=problem, candidate_code=code)))


# ---------- Mock interview ----------
def interview_page():
    st.header("4 · Mock interview")
    if not state.profile:
        st.info("Fill in onboarding first.")
        return

    p = state.profile
    col1, col2, col3 = st.columns([2, 2, 1])
    company = col1.selectbox("Company", p["targetCompanies"] or ["a top tech company"])
    kind = col2.radio("Type", ["Technical", "HR"], horizontal=True)
    if col3.button("Start / restart", type="primary"):
        topic = state.get("current_topic") or (all_topics()[0][1]["name"] if all_topics() else "core DSA")
        opening = (
            f"technical, tied to this week's prep topic: {topic}, and ideally connected to one of their projects."
            if kind == "Technical"
            else "behavioral/HR, grounded in a specific project or experience from their resume."
        )
        system = prompts.MOCK_INTERVIEW.format(
            interview_type=kind,
            target_role=p["targetRole"],
            target_company=company,
            opening_hint=opening,
            resume_json=resume_json(),
            profile_json=profile_json(),
        )
        state.verdict_shown = False
        state.interview = [{"role": "system", "content": system}, {"role": "user", "content": "I'm ready. Please begin."}]
        with st.spinner("Interviewer is joining…"):
            state.interview.append({"role": "assistant", "content": chat(state.interview, model=CHAT_MODEL)})

    for m in state.interview[2:]:
        is_verdict = m["role"] == "assistant" and "verdict" in m["content"].lower()
        with st.chat_message(m["role"], avatar="🧑‍💼" if m["role"] == "assistant" else None):
            if is_verdict:
                if not state.get("verdict_shown"):
                    st.balloons()
                    state.verdict_shown = True
                with st.container(border=True):
                    st.markdown(m["content"])
            else:
                st.markdown(m["content"])

    if state.interview and (answer := st.chat_input("Your answer")):
        state.interview.append({"role": "user", "content": answer})
        with st.spinner("Interviewer is thinking…"):
            state.interview.append({"role": "assistant", "content": chat(state.interview, model=CHAT_MODEL)})
        st.rerun()


PAGES = {
    "Onboarding": onboarding_page,
    "Roadmap": roadmap_page,
    "Practice": practice_page,
    "Mock interview": interview_page,
}

with st.sidebar:
    st.title("🎯 PrepPilot")
    st.caption("AI interview prep, powered by Sarvam")
    page = st.radio("Go to", list(PAGES), label_visibility="collapsed")
    if state.profile:
        st.divider()
        st.caption(f"{state.profile['targetRole']} · {', '.join(state.profile['targetCompanies'])}")

PAGES[page]()

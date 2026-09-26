import io
import json
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader

import db
import fallback
import prompts
from sarvam_client import CHAT_MODEL, ask, chat, parse_json

app = FastAPI(title="PrepPilot")

VERDICT_MARKER = re.compile(r"\n[#*\s]*verdict", re.IGNORECASE)
VERDICT_NOW = (
    "(Interviewer instruction: the interview is over. Do not ask more questions. "
    'Give only the verdict now, under the heading "## Verdict".)'
)
NO_RESUME ="NONE. The candidate did not upload a resume. Do not mention a resume, projects or past experience."


def load_profile(profile_id):
    row = db.get("profiles", profile_id)
    if not row:
        raise HTTPException(404, "Profile not found")
    return row


@app.get("/api/health")
def health():
    return {"ok": True, "database": "supabase" if db.ENABLED else "memory"}


@app.post("/api/profile")
def create_profile(
    target_role: str = Form(...),
    target_companies: str = Form(""),
    college: str = Form(""),
    year: str = Form(""),
    comfort_level: str = Form("Intermediate"),
    resume: UploadFile | None = File(None),
):
    profile = {
        "targetRole": target_role,
        "targetCompanies": [c.strip() for c in target_companies.split(",") if c.strip()],
        "college": college,
        "year": year,
        "comfortLevel": comfort_level,
    }
    resume_data = None
    if resume and resume.filename:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resume.file.read())).pages)
        if not text.strip():
            raise HTTPException(422, "No text found in that PDF. Is it a scanned image?")
        try:
            resume_data = parse_json(ask(prompts.RESUME_EXTRACTION.format(resume_text=text[:12000])))
        except Exception as e:
            raise HTTPException(502, f"Resume extraction failed: {e}")
    return db.insert("profiles", {"profile": profile, "resume": resume_data})


@app.get("/api/profile/{profile_id}")
def read_profile(profile_id: str):
    return load_profile(profile_id)


class RoadmapRequest(BaseModel):
    profile_id: str
    use_default: bool = False


@app.post("/api/roadmap")
def create_roadmap(req: RoadmapRequest):
    row = load_profile(req.profile_id)
    roadmap, source = fallback.ROADMAP, "default"
    if not req.use_default:
        try:
            roadmap = parse_json(
                ask(
                    prompts.ROADMAP.format(
                        profile_json=json.dumps(row["profile"]), resume_json=json.dumps(row["resume"] or {})
                    )
                )
            )
            source = "sarvam"
        except Exception:
            pass
    db.update("profiles", req.profile_id, {"roadmap": roadmap})
    return {"roadmap": roadmap, "source": source}


class TopicRequest(BaseModel):
    profile_id: str
    topic: str
    category: str


@app.post("/api/topic")
def explain_topic(req: TopicRequest):
    p = load_profile(req.profile_id)["profile"]
    text = ask(
        prompts.TOPIC_PRACTICE.format(
            target_role=p["targetRole"],
            companies=", ".join(p["targetCompanies"]) or "top tech companies",
            level=p["comfortLevel"],
            topic=req.topic,
            category=req.category,
        )
    )
    return {"markdown": text}


class ReviewRequest(BaseModel):
    problem: str
    code: str


@app.post("/api/review")
def review_code(req: ReviewRequest):
    return {"markdown": ask(prompts.CODE_REVIEW.format(problem_statement=req.problem, candidate_code=req.code))}


class InterviewStart(BaseModel):
    profile_id: str
    company: str
    kind: str = "Technical"
    topic: str | None = None


class InterviewReply(BaseModel):
    answer: str


def public_messages(messages):
    return messages[2:]


@app.post("/api/interview")
def start_interview(req: InterviewStart):
    row = load_profile(req.profile_id)
    topic = req.topic or "core DSA"
    opening = (
        f"technical, tied to this week's prep topic: {topic}, and ideally connected to one of their projects."
        if req.kind == "Technical"
        else "behavioral/HR, grounded in a specific project or experience from their resume."
    )
    system = prompts.MOCK_INTERVIEW.format(
        interview_type=req.kind,
        target_role=row["profile"]["targetRole"],
        target_company=req.company,
        opening_hint=opening,
        resume_json=json.dumps(row["resume"]) if row["resume"] else NO_RESUME,
        profile_json=json.dumps(row["profile"]),
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "I'm ready. Please begin."}]
    messages.append({"role": "assistant", "content": chat(messages, model=CHAT_MODEL)})
    session = db.insert(
        "interviews", {"profile_id": req.profile_id, "company": req.company, "kind": req.kind, "messages": messages, "finished": False}
    )
    return {"id": session["id"], "messages": public_messages(messages), "finished": False}


@app.post("/api/interview/{interview_id}/reply")
def reply_interview(interview_id: str, req: InterviewReply):
    session = db.get("interviews", interview_id)
    if not session:
        raise HTTPException(404, "Interview not found")
    if session["finished"]:
        raise HTTPException(409, "Interview already finished")
    messages = session["messages"] + [{"role": "user", "content": req.answer}]
    # Opening question + one follow-up, then the verdict. The model tends to
    # blend these, so the server enforces the turn structure.
    finished = sum(1 for m in messages[2:] if m["role"] == "user") >= 2
    if finished:
        reply = chat(messages + [{"role": "user", "content": VERDICT_NOW}], model=CHAT_MODEL)
    else:
        reply = chat(messages, model=CHAT_MODEL)
        reply = VERDICT_MARKER.split(reply)[0].rstrip()
    messages.append({"role": "assistant", "content": reply})
    db.update("interviews", interview_id, {"messages": messages, "finished": finished})
    return {"id": interview_id, "messages": public_messages(messages), "finished": finished}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")

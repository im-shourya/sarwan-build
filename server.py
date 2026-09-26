import io
import json
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

import auth
import db
import prompts
from sarvam_client import REASONING_MODEL, SarvamError, ask, ask_json, chat, ocr_pdf

app = FastAPI(title="PrepPilot")

MAX_RESUME_BYTES = 5 * 1024 * 1024
LANGUAGES = ("python", "javascript", "java", "cpp")
CATEGORIES = ("DSA", "OS", "System Design")

VERDICT_MARKER = re.compile(r"\n[#*\s]*verdict", re.IGNORECASE)
VERDICT_NOW = (
    "(Interviewer instruction: the interview is over. Do not ask more questions. "
    'Give only the verdict now, under the heading "## Verdict".)'
)
NO_RESUME = "NONE. The candidate did not upload a resume. Do not mention a resume, projects or past experience."

User = Annotated[dict, Depends(auth.current_user)]


@app.exception_handler(SarvamError)
def sarvam_error(request: Request, exc: SarvamError):
    return JSONResponse(status_code=502, content={"detail": "The AI service failed or timed out. Please try again."})


def now():
    return datetime.now(timezone.utc).isoformat()


def find_profile(user):
    rows = db.select("profiles", limit=1, user_id=user["id"])
    return rows[0] if rows else None


def my_profile(user):
    row = find_profile(user)
    if not row:
        raise HTTPException(409, "Complete your profile first")
    return row


def owned(table, row_id, profile, label):
    row = db.get(table, row_id)
    if not row or row["profile_id"] != profile["id"]:
        raise HTTPException(404, f"{label} not found")
    return row


@app.get("/api/health")
def health():
    return {"ok": True, "database": "supabase" if db.ENABLED else "memory"}


# ---------- Accounts ----------
class Credentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    password: str = Field(min_length=6, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=500)


@app.post("/api/auth/signup")
def signup(req: Credentials):
    return auth.sign_up(req.email.lower(), req.password)


@app.post("/api/auth/login")
def login(req: Credentials):
    return auth.sign_in(req.email.lower(), req.password)


@app.post("/api/auth/refresh")
def refresh(req: RefreshRequest):
    return auth.refresh(req.refresh_token)


def public_quiz(q):
    return {"id": q["id"], "topic": q["topic"], "category": q["category"],
            "questions": [{"question": x["question"], "options": x["options"]} for x in q["questions"]]}


@app.get("/api/me")
def me(user: User):
    """Everything the app needs to pick up where the user left off."""
    profile = find_profile(user)
    if not profile:
        return {"user": user, "profile": None, "resume": {}}
    pid = profile["id"]
    open_quiz = next((q for q in db.select("quizzes", limit=5, profile_id=pid) if not q.get("submitted_at")), None)
    last_problem = next(iter(db.select("problems", limit=1, profile_id=pid)), None)
    last_interview = next(iter(db.select("interviews", limit=1, profile_id=pid)), None)
    return {
        "user": user,
        "profile": profile,
        "resume": {
            "quiz": public_quiz(open_quiz) if open_quiz else None,
            "problem": {"id": last_problem["id"], "difficulty": last_problem["difficulty"], **last_problem["problem"]}
            if last_problem else None,
            "interview": {
                "id": last_interview["id"],
                "company": last_interview["company"],
                "kind": last_interview["kind"],
                "messages": last_interview["messages"][2:],
                "finished": last_interview["finished"],
                "score": interview_score(last_interview["messages"][-1]["content"]) if last_interview["finished"] else None,
            } if last_interview else None,
        },
    }


# ---------- Profile & resume ----------
Name = Annotated[str, Form(min_length=1, max_length=100)]
Role = Annotated[str, Form(min_length=1, max_length=100)]
Companies = Annotated[str, Form(max_length=300)]
College = Annotated[str, Form(max_length=200)]
Year = Annotated[str, Form(max_length=20)]
Level = Annotated[str, Form(pattern="^(Beginner|Intermediate|Advanced)$")]
Resume = Annotated[UploadFile | None, File()]


def read_resume(upload):
    """Returns (resume_json, method, warning). Text PDFs are read locally; scanned ones go to Sarvam Vision."""
    data = upload.file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "Resume must be under 5 MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Resume must be a PDF.")

    try:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        text = ""
    method = "text"
    if len(text.strip()) < 50:
        text, method = ocr_pdf(data), "sarvam-vision"
    if not text.strip():
        return None, method, "Couldn't find any text in that PDF. Saved your profile without it."

    def validate(r):
        assert isinstance(r.get("skills"), list) and isinstance(r.get("projects"), list)

    resume = ask_json(prompts.RESUME_EXTRACTION.format(resume_text=text[:12000]), validate)
    return resume, method, None


@app.put("/api/profile")
def save_profile(
    user: User, name: Name, target_role: Role, target_companies: Companies = "", college: College = "",
    year: Year = "", comfort_level: Level = "Intermediate", resume: Resume = None,
):
    fields = {
        "profile": {
            "name": name.strip(),
            "targetRole": target_role.strip(),
            "targetCompanies": [c.strip() for c in target_companies.split(",") if c.strip()],
            "college": college.strip(),
            "year": year,
            "comfortLevel": comfort_level,
        },
        "updated_at": now(),
    }
    method, warning = None, None
    if resume and resume.filename:
        resume_data, method, warning = read_resume(resume)
        if resume_data:
            fields["resume"] = {**resume_data, "source": method}
    existing = find_profile(user)
    if existing:
        row = db.update("profiles", existing["id"], fields)
    else:
        row = db.insert("profiles", {"user_id": user["id"], "resume": None, "completed_topics": [], **fields})
    return {**row, "resumeMethod": method, "warning": warning}


def interview_score(verdict):
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", verdict)
    return float(m.group(1)) if m else None


@app.get("/api/progress")
def progress(user: User):
    pid = my_profile(user)["id"]
    quizzes = [q for q in db.select("quizzes", "id,created_at,topic,category,score,total,submitted_at", profile_id=pid)
               if q.get("submitted_at")]
    submissions = db.select("submissions", "id,created_at,language,review,problem_id", profile_id=pid)
    titles = {p["id"]: p["problem"].get("title") for p in db.select("problems", "id,problem", profile_id=pid)}
    interviews = db.select("interviews", "id,created_at,company,kind,finished,messages", profile_id=pid)

    best = {}
    for q in quizzes:
        pct = round(100 * q["score"] / q["total"])
        best[q["topic"]] = max(best.get(q["topic"], 0), pct)
    return {
        "bestQuizByTopic": best,
        "quizzes": quizzes,
        "submissions": [
            {
                "id": s["id"], "created_at": s["created_at"], "language": s["language"],
                "verdict": s["review"].get("verdict"), "score": s["review"].get("score"),
                "title": titles.get(s["problem_id"]) or "Custom problem",
            }
            for s in submissions
        ],
        "interviews": [
            {
                "id": i["id"], "created_at": i["created_at"], "company": i["company"], "kind": i["kind"],
                "score": interview_score(i["messages"][-1]["content"]) if i["finished"] else None,
            }
            for i in interviews
        ],
    }


# ---------- Roadmap ----------
def validate_roadmap(r):
    assert len(r["weeks"]) >= 1
    for w in r["weeks"]:
        assert w["topics"] and all(t["category"] in CATEGORIES for t in w["topics"])


@app.post("/api/roadmap")
def create_roadmap(user: User):
    row = my_profile(user)
    roadmap = ask_json(
        prompts.ROADMAP.format(profile_json=json.dumps(row["profile"]), resume_json=json.dumps(row["resume"] or {})),
        validate_roadmap,
    )
    # A new roadmap has new topics, so completion starts over.
    db.update("profiles", row["id"], {"roadmap": roadmap, "completed_topics": [], "updated_at": now()})
    return {"roadmap": roadmap, "completed_topics": []}


class CompleteRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    done: bool = True


@app.post("/api/roadmap/complete")
def complete_topic(req: CompleteRequest, user: User):
    row = my_profile(user)
    done = [t for t in row.get("completed_topics") or [] if t != req.topic]
    if req.done:
        done.append(req.topic)
    db.update("profiles", row["id"], {"completed_topics": done, "updated_at": now()})
    return {"completed_topics": done}


# ---------- Learn ----------
class TopicRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    category: str = Field(max_length=50)


@app.post("/api/topic")
def explain_topic(req: TopicRequest, user: User):
    p = my_profile(user)["profile"]
    text = ask(
        prompts.TOPIC_EXPLAIN.format(
            target_role=p["targetRole"], companies=", ".join(p["targetCompanies"]) or "top tech companies",
            level=p["comfortLevel"], topic=req.topic, category=req.category,
        )
    )
    return {"markdown": text}


# ---------- Quiz ----------
class QuizRequest(TopicRequest):
    count: int = Field(5, ge=3, le=10)


class QuizSubmit(BaseModel):
    answers: list[int | None] = Field(max_length=10)


def validate_quiz(q):
    assert len(q["questions"]) >= 3
    for item in q["questions"]:
        assert item["question"] and len(item["options"]) == 4
        assert isinstance(item["answerIndex"], int) and 0 <= item["answerIndex"] < 4


@app.post("/api/quiz")
def create_quiz(req: QuizRequest, user: User):
    row = my_profile(user)
    p = row["profile"]
    quiz = ask_json(
        prompts.QUIZ.format(
            target_role=p["targetRole"], level=p["comfortLevel"],
            topic=req.topic, category=req.category, count=req.count,
        ),
        validate_quiz,
    )
    questions = quiz["questions"][: req.count]
    saved = db.insert(
        "quizzes",
        {"profile_id": row["id"], "topic": req.topic, "category": req.category,
         "questions": questions, "total": len(questions)},
    )
    # Answers stay on the server until the quiz is submitted.
    return public_quiz(saved)


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: str, req: QuizSubmit, user: User):
    quiz = owned("quizzes", quiz_id, my_profile(user), "Quiz")
    if quiz.get("submitted_at"):
        raise HTTPException(409, "Quiz already submitted")
    questions = quiz["questions"]
    if len(req.answers) != len(questions):
        raise HTTPException(422, f"Expected {len(questions)} answers")
    results = [{**q, "chosen": a, "correct": a == q["answerIndex"]} for q, a in zip(questions, req.answers)]
    score = sum(r["correct"] for r in results)
    db.update("quizzes", quiz_id, {"answers": req.answers, "score": score, "submitted_at": now()})
    return {"id": quiz_id, "topic": quiz["topic"], "score": score, "total": len(questions), "results": results}


# ---------- Coding ----------
class ProblemRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    difficulty: str = Field("Medium", pattern="^(Easy|Medium|Hard)$")


def validate_problem(prob):
    assert prob["title"] and prob["statement"]
    assert all(prob["starterCode"].get(lang) for lang in LANGUAGES)


@app.post("/api/problem")
def create_problem(req: ProblemRequest, user: User):
    row = my_profile(user)
    p = row["profile"]
    problem = ask_json(
        prompts.PROBLEM.format(
            target_role=p["targetRole"], level=p["comfortLevel"], topic=req.topic, difficulty=req.difficulty
        ),
        validate_problem,
    )
    saved = db.insert(
        "problems",
        {"profile_id": row["id"], "topic": req.topic, "difficulty": req.difficulty, "problem": problem},
    )
    return {"id": saved["id"], "difficulty": req.difficulty, **problem}


class ReviewRequest(BaseModel):
    problem_id: str | None = None
    problem: str | None = Field(None, max_length=4000)  # used when there is no generated problem
    language: str = Field(pattern="^(python|javascript|java|cpp)$")
    code: str = Field(min_length=1, max_length=20000)


def problem_text(prob):
    examples = "\n".join(f"Input: {e['input']}\nOutput: {e['output']}" for e in prob.get("examples", []))
    constraints = "\n".join(f"- {c}" for c in prob.get("constraints", []))
    return f"{prob['title']}\n\n{prob['statement']}\n\nExamples:\n{examples}\n\nConstraints:\n{constraints}"


def validate_review(r):
    assert r["verdict"] in ("correct", "partially correct", "incorrect")
    assert r["timeComplexity"] and r["spaceComplexity"] and isinstance(r["issues"], list)


@app.post("/api/review")
def review_code(req: ReviewRequest, user: User):
    row = my_profile(user)
    if req.problem_id:
        statement = problem_text(owned("problems", req.problem_id, row, "Problem")["problem"])
    elif req.problem and req.problem.strip():
        statement = req.problem
    else:
        raise HTTPException(422, "Generate a problem or describe the problem you solved.")
    review = ask_json(
        prompts.CODE_REVIEW.format(language=req.language, problem_statement=statement, candidate_code=req.code),
        validate_review,
        model=REASONING_MODEL,
    )
    saved = db.insert(
        "submissions",
        {"profile_id": row["id"], "problem_id": req.problem_id, "language": req.language,
         "code": req.code, "review": review},
    )
    return {"id": saved["id"], **review}


# ---------- Mock interview ----------
class InterviewStart(BaseModel):
    company: str = Field(min_length=1, max_length=100)
    kind: str = Field("Technical", pattern="^(Technical|HR)$")
    topic: str | None = Field(None, max_length=200)


class InterviewReply(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


@app.post("/api/interview")
def start_interview(req: InterviewStart, user: User):
    row = my_profile(user)
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
    messages.append({"role": "assistant", "content": chat(messages)})
    session = db.insert(
        "interviews",
        {"profile_id": row["id"], "company": req.company, "kind": req.kind, "messages": messages, "finished": False},
    )
    return {"id": session["id"], "messages": messages[2:], "finished": False, "score": None}


@app.post("/api/interview/{interview_id}/reply")
def reply_interview(interview_id: str, req: InterviewReply, user: User):
    session = owned("interviews", interview_id, my_profile(user), "Interview")
    if session["finished"]:
        raise HTTPException(409, "Interview already finished")
    messages = session["messages"] + [{"role": "user", "content": req.answer}]
    # Opening question + one follow-up, then the verdict. The model tends to
    # blend these, so the server enforces the turn structure.
    finished = sum(1 for m in messages[2:] if m["role"] == "user") >= 2
    if finished:
        reply = chat(messages + [{"role": "user", "content": VERDICT_NOW}])
    else:
        reply = VERDICT_MARKER.split(chat(messages))[0].rstrip()
    messages.append({"role": "assistant", "content": reply})
    db.update("interviews", interview_id, {"messages": messages, "finished": finished})
    return {
        "id": interview_id,
        "messages": messages[2:],
        "finished": finished,
        "score": interview_score(reply) if finished else None,
    }


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")

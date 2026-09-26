# AI-Personalized Coding & Interview Prep Platform — Build Spec

Built for the Sarvam AI build-along. Uses Sarvam-105B (reasoning/generation), Sarvam Vision (document/image parsing), and optionally Saaras (speech-to-text) / Bulbul (text-to-speech) as stretch goals.

Positioned as the candidate-facing companion to RECRUIT.AI — RECRUIT.AI screens candidates for a role; this platform *prepares* candidates for that kind of screening.

---

## 1. Core Concept

A platform where a user logs in, gets a personalized prep roadmap based on their goals, and practices for interviews through generated topics, DSA questions, code review, and mock interviews — including resume-aware, company/role-specific mock interviews.

## 2. Full Feature Set (as described)

- **Onboarding**: user provides target role, target companies, college/year, current comfort level — used to generate a personalized roadmap.
- **Roadmap generation**: AI generates a weekly/daily roadmap of topics and challenges based on onboarding profile.
- **Topic breakdown**: for each roadmap topic, generate an explanation plus practice questions.
- **DSA practice**: user submits a solution; system analyzes correctness, time complexity, space complexity, and suggests a better approach (a "full DSA practice guide" experience).
- **Fundamentals coverage**: OS, DSA, and System Design as core topic categories, not separate modules.
- **Resume upload & analysis**: user uploads a resume; system extracts projects, skills, and experience.
- **Mock interviews**:
  - HR interviews and technical interviews.
  - Company- and role-specific: interview questions reference the target company/role.
  - Resume-aware: questions reference the user's actual listed projects/experience.
- **Camera facial-expression feature** (stretch/future): use webcam to read facial expressions/engagement during a mock interview.

## 3. What Fits in a 60–80 Minute Build (MVP Scope)

Given the time constraint, the following scope was agreed as realistic, with reasoning for each cut.

### Keep
| Feature | Why it survives |
|---|---|
| Onboarding form (role, companies, college, level) | Trivial to build, feeds everything else |
| Resume upload + extraction | One Sarvam Vision/text-extraction call; high demo payoff |
| One-call roadmap generator (DSA + OS + System Design topics) | Single LLM call, no extra engineering per subject |
| Topic → practice question generator | Single LLM call per topic |
| Code review (paste solution → LLM reasons about correctness/complexity/better approach) | LLM reasoning only, no sandbox needed |
| Resume + role/company-aware mock interview (chat-based) | Core differentiator; combines Vision-extracted resume with 105B reasoning |

### Cut or fake for this build
| Feature | Why it's cut | Alternative |
|---|---|---|
| Real code execution/compiler for DSA (actual runtime/space measurement) | Needs a sandboxed executor (Judge0/Piston/custom container) — infra, not a prompt | LLM reads pasted code and reasons about complexity/approach instead of running it |
| Live camera facial-expression analysis | Not a Sarvam API capability; needs a separate face-landmark/emotion model (MediaPipe, face-api.js) plus real testing time | Fake with a static "engagement: high/medium" badge, or mark as "planned feature" on the pitch slide, not built live |
| Voice-based mock interview (Saaras/Bulbul) | STT/TTS wiring is a real time sink for an 80-min build | Text-chat interview for MVP; voice is a stretch goal if time remains |

## 4. Build Order (Happy Path)

1. **Onboarding + resume upload** (~10 min) — profile form + resume upload; extract resume text via Sarvam Vision (or a plain PDF-text library if resume is text-based).
2. **Roadmap generation** (~15–20 min) — one Sarvam-105B call producing a 4-week roadmap JSON covering DSA/OS/System Design topics tailored to the profile + resume.
3. **Code review** (~10–15 min) — textarea for pasted code; Sarvam-105B reasons about correctness, time/space complexity, and a better approach.
4. **Resume + role-aware mock interview** (~15–20 min) — chat UI; system prompt includes resume summary + target company/role so questions reference specifics; ends with a structured verdict (strengths, gaps, score).
5. **Wire the one happy path** (~10 min) — onboarding+resume → roadmap → topic → code review OR mock interview → verdict. Hardcode fallback roadmap JSON in case a live API call is slow.
6. **Polish only the roadmap view and the interview verdict screen** (~10 min) — these are the two screens judges will remember.

## 5. System Prompts

### 5.1 Resume Extraction Prompt

Use after Sarvam Vision (or a PDF-text extractor) has produced raw resume text.

```
You are a resume-parsing assistant. Given raw resume text, extract a structured summary as JSON with this exact shape:

{
  "name": string,
  "targetRoleHint": string | null,       // any explicit role mentioned, else null
  "education": [{ "institution": string, "degree": string, "year": string | null }],
  "skills": [string],
  "projects": [{ "name": string, "description": string, "techStack": [string] }],
  "experience": [{ "role": string, "org": string, "duration": string | null, "summary": string }]
}

Rules:
- Only include information explicitly present in the text. Do not invent details.
- Keep each project/experience description to one sentence.
- Return ONLY the JSON object, no preamble, no markdown fences.

Resume text:
"""
{resume_text}
"""
```

### 5.2 Roadmap Generation Prompt

```
You are a technical interview prep coach. Given a candidate profile, generate a 4-week preparation roadmap as JSON with this exact shape:

{
  "weeks": [
    {
      "weekNumber": number,
      "focus": string,
      "topics": [
        { "name": string, "category": "DSA" | "OS" | "System Design", "why": string }
      ],
      "dailyChallenges": [string]
    }
  ]
}

Guidance:
- Tailor topic difficulty and depth to the candidate's stated comfort level.
- If target companies are known, weight topics toward what those companies commonly ask.
- If resume data is provided, favor topics that reinforce or extend the candidate's existing skills/projects.
- Cover a mix of DSA, OS fundamentals, and System Design across the 4 weeks — don't front-load one category.
- Return ONLY the JSON object, no preamble, no markdown fences.

Candidate profile:
"""
{profile_json}
"""

Resume summary (if available):
"""
{resume_json}
"""
```

### 5.3 Code Review Prompt (DSA practice, no execution)

```
You are a senior engineer reviewing a candidate's solution to a DSA problem. You are NOT executing this code — reason about it purely by reading it.

Given the problem statement and the candidate's submitted code, respond with:
1. Correctness: does the logic solve the stated problem? Note any edge cases it misses.
2. Time complexity: state Big-O and briefly justify it from the code structure.
3. Space complexity: state Big-O and briefly justify it.
4. A better approach (if one exists): describe it in plain language, and explain the complexity improvement it offers. If the current approach is already optimal, say so.

Keep the whole response under 200 words. Be direct and specific to this code, not generic advice.

Problem statement:
"""
{problem_statement}
"""

Candidate's code:
"""
{candidate_code}
"""
```

### 5.4 Resume + Role-Aware Mock Interview Prompt (system prompt for the chat)

```
You are conducting a mock interview for the role of {target_role} at {target_company_or_type}. You have the candidate's resume summary below — use it to ask specific, grounded questions (e.g. reference an actual project or skill listed), not generic ones.

Interview flow:
1. Ask one opening question — either technical (tied to this week's prep topic: {current_topic}) or behavioral/HR, chosen based on what fits the role.
2. Read the candidate's answer. Ask exactly ONE natural follow-up question that probes deeper into something specific they said.
3. After the follow-up is answered, end the interview and give a structured verdict:
   - Strengths (1-3 bullet points)
   - Gaps or areas to improve (1-3 bullet points)
   - Overall score out of 10 with one-sentence justification

Do not ask more than 2 questions total before giving the verdict — keep this interview short and demoable.

Candidate resume summary:
"""
{resume_json}
"""

Candidate profile:
"""
{profile_json}
"""
```

## 6. Notes / Open Items

- Camera facial-expression feature: parked as a future feature, not part of this build.
- Real code execution sandbox: parked as a future upgrade path (Judge0/Piston) if the project continues past the hackathon.
- Voice interview (Saaras + Bulbul): stretch goal if time remains after the core text-based path works.

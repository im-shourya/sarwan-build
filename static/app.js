const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const md = (text) => DOMPurify.sanitize(marked.parse(text || ""));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---------- Local persistence (session + UI position) ----------
const local = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
};
let session = local.get("session", null);
const ui = Object.assign({ view: "home", tab: "learn", topic: null, language: "python" }, local.get("ui", {}));
const saveUi = () => local.set("ui", ui);
const drafts = local.get("drafts", {}); // { [problemId]: { [language]: code } }
const saveDrafts = () => local.set("drafts", drafts);

// ---------- App state ----------
let user = null;
let profile = null;     // profiles row
let progressData = null;
let quiz = null;        // open quiz { id, topic, questions }
let quizState = null;   // { index, answers[] } for the open quiz
let quizResult = null;  // graded result
let problem = null;
let interview = null;

// ---------- Helpers ----------
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4500);
}

async function refreshSession() {
  if (!session?.refresh_token) return false;
  const res = await fetch("/api/auth/refresh", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  });
  if (!res.ok) return false;
  session = await res.json();
  local.set("session", session);
  return true;
}

async function api(path, body, { method, form, retry = true } = {}) {
  const headers = form || body === undefined ? {} : { "Content-Type": "application/json" };
  if (session) headers.Authorization = `Bearer ${session.access_token}`;
  const res = await fetch(path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers,
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  if (res.status === 401 && retry && session && await refreshSession()) {
    return api(path, body, { method, form, retry: false });
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && session) {
    signOut("Your session expired. Please sign in again.");
    throw new Error("Session expired");
  }
  if (!res.ok) {
    // FastAPI validation errors arrive as a list.
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ") : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return data;
}

async function busy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try { await fn(); } catch (e) { if (e.message !== "Session expired") toast(e.message); } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const pct = (n) => `${Math.round(n)}%`;

function topics() {
  return (profile?.roadmap?.weeks || []).flatMap((w) => w.topics.map((t) => ({ ...t, week: w.weekNumber })));
}
const completed = () => new Set(profile?.completed_topics || []);
function currentTopic() {
  return topics().find((t) => t.name === ui.topic) || topics()[0] || null;
}
function nextTopic() {
  const done = completed();
  return topics().find((t) => !done.has(t.name)) || null;
}

// ---------- Navigation ----------
function show(view) {
  if (!profile && view !== "profile") view = "profile";
  ui.view = view;
  saveUi();
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "home") renderHome();
  if (view === "practice") setTimeout(() => editor.refresh());
  window.scrollTo({ top: 0 });
}
$$("#nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

function showTab(tab) {
  ui.tab = tab;
  saveUi();
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${tab}`));
  if (tab === "code") setTimeout(() => editor.refresh());
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

function practise(topicName, tab) {
  ui.topic = topicName;
  renderPractice();
  show("practice");
  showTab(tab || ui.tab);
}

// ---------- Auth ----------
let authMode = "login";
$$(".auth-tabs button").forEach((b) => b.addEventListener("click", () => {
  authMode = b.dataset.mode;
  $$(".auth-tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $("#auth-submit").textContent = authMode === "login" ? "Sign in" : "Create account";
  $("#auth-form").password.autocomplete = authMode === "login" ? "current-password" : "new-password";
}));

$("#auth-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target;
  busy(e.submitter, authMode === "login" ? "Signing in…" : "Creating account…", async () => {
    session = await api(`/api/auth/${authMode}`, { email: f.email.value.trim(), password: f.password.value });
    local.set("session", session);
    f.reset();
    await boot();
  });
});

function signOut(message) {
  session = user = profile = quiz = quizState = quizResult = problem = interview = progressData = null;
  local.set("session", null);
  local.set("ui", null);
  $("#app").hidden = true;
  $("#auth").hidden = false;
  if (message) toast(message);
}
$("#logout").addEventListener("click", () => signOut());

// ---------- Editor ----------
const MODES = { python: "python", javascript: "javascript", java: "text/x-java", cpp: "text/x-c++src" };
const editor = CodeMirror($("#editor"), {
  mode: MODES[ui.language],
  lineNumbers: true,
  indentUnit: 4,
  tabSize: 4,
  indentWithTabs: false,
  matchBrackets: true,
  autoCloseBrackets: true,
  extraKeys: {
    Tab: (cm) => (cm.somethingSelected() ? cm.indentSelection("add") : cm.replaceSelection(" ".repeat(cm.getOption("indentUnit")))),
    "Shift-Tab": (cm) => cm.indentSelection("subtract"),
    "Ctrl-Enter": () => $("#review").click(),
    "Cmd-Enter": () => $("#review").click(),
  },
});
$("#language").value = ui.language;

let loadingEditor = false;
function loadEditor() {
  const saved = problem && drafts[problem.id]?.[ui.language];
  loadingEditor = true; // programmatic loads are not user edits
  editor.setValue(saved ?? problem?.starterCode?.[ui.language] ?? "");
  loadingEditor = false;
}
function saveDraft() {
  clearTimeout(saveDraft.timer);
  if (!problem) return;
  drafts[problem.id] = { ...drafts[problem.id], [ui.language]: editor.getValue() };
  // Keep only the most recent few problems' drafts.
  const ids = Object.keys(drafts);
  if (ids.length > 5) ids.slice(0, ids.length - 5).forEach((id) => delete drafts[id]);
  saveDrafts();
}
editor.on("change", () => {
  if (loadingEditor || !problem) return;
  clearTimeout(saveDraft.timer);
  saveDraft.timer = setTimeout(saveDraft, 400);
});
window.addEventListener("beforeunload", saveDraft);
$("#language").addEventListener("change", (e) => {
  saveDraft(); // flush edits for the language we are leaving
  ui.language = e.target.value;
  saveUi();
  editor.setOption("mode", MODES[ui.language]);
  loadEditor();
});
$("#reset-code").addEventListener("click", () => {
  if (problem && confirm("Reset to the starter code? Your changes in this language will be lost.")) {
    editor.setValue(problem.starterCode[ui.language] || "");
  }
});

// ---------- Render: shell ----------
function renderShell() {
  $("#account-email").textContent = user?.email || "";
  const all = topics().length;
  const done = topics().filter((t) => completed().has(t.name)).length;
  $("#side-progress").innerHTML = all
    ? `<b>${pct((100 * done) / all)}</b>Roadmap complete<div class="bar" style="margin-top:8px"><i style="width:${(100 * done) / all}%"></i></div>`
    : "";
  if (profile) {
    const companies = profile.profile.targetCompanies;
    $("#company").innerHTML = (companies.length ? companies : ["a top tech company"]).map((c) => `<option>${esc(c)}</option>`).join("");
  }
}

// ---------- Render: home ----------
async function loadProgress() {
  try { progressData = await api("/api/progress"); } catch { return; }
  // Views showing progress may have rendered before this arrived.
  renderRoadmap();
  if (ui.view === "home") renderHome();
}

function renderHome() {
  if (!profile) return;
  const p = profile.profile;
  const hour = new Date().getHours();
  $("#greeting").textContent = `${hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"}, ${p.name.split(" ")[0]}`;
  $("#greeting-sub").textContent = `${p.targetRole}${p.targetCompanies.length ? " · " + p.targetCompanies.join(", ") : ""}`;

  // Continue card: the most useful next action.
  let cont;
  if (quiz && quizState) {
    cont = { eyebrow: "Quiz in progress", title: quiz.topic, text: `Question ${quizState.index + 1} of ${quiz.questions.length}`, label: "Resume quiz", go: () => practise(quiz.topic, "quiz") };
  } else if (interview && !interview.finished) {
    cont = { eyebrow: "Interview in progress", title: `${interview.kind} interview · ${interview.company}`, text: "Pick up where you left off.", label: "Resume interview", go: () => show("interview") };
  } else if (!topics().length) {
    cont = { eyebrow: "Get started", title: "Generate your roadmap", text: "A four-week plan across DSA, OS and System Design, tailored to you.", label: "Open roadmap", go: () => show("roadmap") };
  } else if (nextTopic()) {
    const t = nextTopic();
    cont = { eyebrow: `Up next · Week ${t.week}`, title: t.name, text: t.why, label: "Start practising", go: () => practise(t.name, "learn") };
  } else {
    cont = { eyebrow: "Roadmap complete", title: "Every topic is done", text: "Take a mock interview to put it together.", label: "Mock interview", go: () => show("interview") };
  }
  $("#continue").innerHTML = `
    <div class="card continue">
      <div><div class="eyebrow">${esc(cont.eyebrow)}</div><h2>${esc(cont.title)}</h2><p>${esc(cont.text)}</p></div>
      <button class="primary" id="continue-go">${esc(cont.label)}</button>
    </div>`;
  $("#continue-go").addEventListener("click", cont.go);

  const all = topics().length;
  const done = topics().filter((t) => completed().has(t.name)).length;
  const pd = progressData || { quizzes: [], submissions: [], interviews: [] };
  const quizPct = avg(pd.quizzes.map((q) => (100 * q.score) / q.total));
  const codeAvg = avg(pd.submissions.map((s) => s.score).filter((x) => x != null));
  const ivAvg = avg(pd.interviews.map((i) => i.score).filter((x) => x != null));
  const stat = (value, label, fill) => `<div class="stat"><b>${value}</b><span>${label}</span>${fill != null ? `<div class="bar"><i style="width:${fill}%"></i></div>` : ""}</div>`;
  $("#stats").innerHTML = [
    stat(all ? `${done}/${all}` : "–", "Topics complete", all ? (100 * done) / all : 0),
    stat(quizPct == null ? "–" : pct(quizPct), `Quiz accuracy · ${pd.quizzes.length} taken`, quizPct),
    stat(codeAvg == null ? "–" : codeAvg.toFixed(1), `Avg code score · ${pd.submissions.length} reviewed`, codeAvg == null ? null : codeAvg * 10),
    stat(ivAvg == null ? "–" : ivAvg.toFixed(1), `Avg interview score · ${pd.interviews.filter((i) => i.score != null).length} done`, ivAvg == null ? null : ivAvg * 10),
  ].join("");

  const items = [
    ...pd.quizzes.map((q) => ({ at: q.created_at, text: `Quiz · ${q.topic}`, meta: `${q.score}/${q.total}` })),
    ...pd.submissions.map((s) => ({ at: s.created_at, text: `Code · ${s.title}`, meta: `${s.verdict} · ${s.score}/10` })),
    ...pd.interviews.map((i) => ({ at: i.created_at, text: `${i.kind} interview · ${i.company}`, meta: i.score != null ? `${i.score}/10` : "in progress" })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 8);
  $("#activity").innerHTML = items.length
    ? `<ul class="history">${items.map((i) => `<li><span>${esc(i.text)}</span><span>${esc(i.meta)} · ${when(i.at)}</span></li>`).join("")}</ul>`
    : `<div class="empty">Nothing yet. Your quizzes, reviews and interviews will show up here.</div>`;
}

// ---------- Render: roadmap ----------
function renderRoadmap() {
  const weeks = profile?.roadmap?.weeks;
  $("#gen-roadmap").textContent = weeks ? "Regenerate" : "Generate roadmap";
  if (!weeks) {
    $("#roadmap-progress").innerHTML = "";
    $("#roadmap").innerHTML = `<div class="empty">No roadmap yet. Generate one from your profile. It takes a few seconds.</div>`;
    return;
  }
  const done = completed();
  const best = progressData?.bestQuizByTopic || {};
  const all = topics().length;
  const doneCount = topics().filter((t) => done.has(t.name)).length;
  $("#roadmap-progress").innerHTML = `<div class="roadmap-progress"><div class="bar"><i style="width:${(100 * doneCount) / all}%"></i></div><b>${doneCount} of ${all} topics done</b></div>`;
  $("#roadmap").innerHTML = weeks.map((w) => {
    const wDone = w.topics.filter((t) => done.has(t.name)).length;
    return `
    <article class="card week">
      <div class="num"><span>Week ${w.weekNumber}</span><span>${wDone}/${w.topics.length}</span></div>
      <h3>${esc(w.focus)}</h3>
      <div class="bar"><i style="width:${(100 * wDone) / w.topics.length}%"></i></div>
      ${w.topics.map((t) => `
        <div class="topic-row ${done.has(t.name) ? "done" : ""}">
          <input type="checkbox" data-done="${esc(t.name)}" ${done.has(t.name) ? "checked" : ""} aria-label="Mark ${esc(t.name)} done">
          <button data-open="${esc(t.name)}">
            <span class="topic-meta"><span class="tag ${esc(t.category.split(" ")[0])}">${esc(t.category)}</span>
            ${best[t.name] != null ? `<span class="badge ${best[t.name] >= 70 ? "good" : ""}">Quiz ${best[t.name]}%</span>` : ""}</span>
            <strong>${esc(t.name)}</strong>
            <p>${esc(t.why)}</p>
          </button>
        </div>`).join("")}
      <ol class="challenges">${(w.dailyChallenges || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ol>
    </article>`;
  }).join("");
  $("#roadmap").style.gridTemplateColumns = window.innerWidth > 1100 ? `repeat(${weeks.length}, minmax(0, 1fr))` : "";
  $$("#roadmap [data-open]").forEach((b) => b.addEventListener("click", () => practise(b.dataset.open)));
  $$("#roadmap [data-done]").forEach((c) => c.addEventListener("change", () => setDone(c.dataset.done, c.checked)));
}

async function setDone(topic, done) {
  try {
    const res = await api("/api/roadmap/complete", { topic, done });
    profile.completed_topics = res.completed_topics;
    renderRoadmap();
    renderPractice();
    renderShell();
    if (done) toast(`Marked "${topic}" done.`);
  } catch (e) {
    toast(e.message);
    renderRoadmap();
  }
}

// ---------- Render: practice ----------
function renderPractice() {
  const list = topics();
  if (!list.length) {
    $("#topic-select").innerHTML = `<option value="">Generate a roadmap first</option>`;
    $("#mark-done").hidden = true;
    return;
  }
  const t = currentTopic();
  ui.topic = t.name;
  saveUi();
  const done = completed();
  $("#topic-select").innerHTML = list.map((x) =>
    `<option value="${esc(x.name)}" ${x.name === t.name ? "selected" : ""}>${done.has(x.name) ? "✓ " : ""}Week ${x.week} · ${esc(x.name)}</option>`).join("");
  $("#mark-done").hidden = false;
  $("#mark-done").textContent = done.has(t.name) ? "Mark not done" : "Mark done";
  $("#practice-sub").textContent = `${t.category} · ${t.why}`;
  renderQuiz();
}

$("#topic-select").addEventListener("change", (e) => {
  ui.topic = e.target.value;
  $("#topic-out").innerHTML = `<div class="empty">Get a focused explanation of this topic, written for your target role.</div>`;
  if (!quiz) quizResult = null;
  renderPractice();
});
$("#mark-done").addEventListener("click", () => {
  const t = currentTopic();
  if (t) setDone(t.name, !completed().has(t.name));
});

$("#explain").addEventListener("click", (e) => {
  const t = currentTopic();
  if (!t) return toast("Generate a roadmap first.");
  busy(e.target, "Thinking…", async () => {
    const res = await api("/api/topic", { topic: t.name, category: t.category });
    $("#topic-out").innerHTML = md(res.markdown);
  });
});

// ---------- Quiz ----------
const LETTERS = ["A", "B", "C", "D"];

function saveQuizState() {
  local.set("quizState", quiz ? { id: quiz.id, ...quizState } : null);
}

function renderQuiz() {
  const box = $("#quiz");
  const t = currentTopic();

  if (quizResult && !quiz) {
    const r = quizResult;
    const percent = Math.round((100 * r.score) / r.total);
    box.innerHTML = `
      <div class="result-head">
        <div class="result-score">${r.score}/${r.total}</div>
        <div><h2 style="margin:0">${percent >= 80 ? "Strong result" : percent >= 50 ? "Getting there" : "Worth another pass"}</h2>
        <p>${esc(r.topic)} · ${percent}%</p></div>
      </div>
      <div class="actions" style="margin-bottom:8px">
        <button class="primary" id="quiz-again">New quiz</button>
        ${percent >= 70 && !completed().has(r.topic) ? `<button id="quiz-done">Mark topic done</button>` : ""}
      </div>
      ${r.results.map((q, i) => `
        <div class="review-q">
          <div class="q-text">${i + 1}. ${esc(q.question)}</div>
          <div class="opts">${q.options.map((o, oi) => `
            <div class="opt ${oi === q.answerIndex ? "right" : oi === q.chosen ? "wrong" : ""}"><span class="key">${LETTERS[oi]}</span><span>${esc(o)}</span></div>`).join("")}</div>
          <div class="explain"><b>${q.correct ? "Correct." : q.chosen == null ? "Skipped." : "Incorrect."}</b> ${esc(q.explanation)}</div>
        </div>`).join("")}`;
    $("#quiz-again").addEventListener("click", () => { quizResult = null; renderQuiz(); });
    $("#quiz-done")?.addEventListener("click", () => setDone(r.topic, true));
    return;
  }

  if (!quiz) {
    box.innerHTML = `
      <div class="quiz-start">
        <div><h2 style="margin-bottom:4px">Quiz: ${esc(t?.name || "pick a topic")}</h2>
        <p class="lede" style="margin:0">Multiple choice, one question at a time. Answers are revealed when you submit.</p></div>
        <label style="grid-auto-flow:column;align-items:center;justify-content:start">Questions
          <select id="quiz-count" style="width:auto"><option>5</option><option>8</option><option>10</option></select>
        </label>
        <button class="primary" id="new-quiz">Start quiz</button>
      </div>`;
    $("#new-quiz").addEventListener("click", (e) => {
      if (!t) return toast("Generate a roadmap first.");
      busy(e.target, "Writing questions…", async () => {
        quiz = await api("/api/quiz", { topic: t.name, category: t.category, count: Number($("#quiz-count").value) });
        quizState = { index: 0, answers: quiz.questions.map(() => null) };
        saveQuizState();
        renderQuiz();
      });
    });
    return;
  }

  const { index, answers } = quizState;
  const q = quiz.questions[index];
  const answered = answers.filter((a) => a != null).length;
  const last = index === quiz.questions.length - 1;
  box.innerHTML = `
    <div class="quiz-top"><span>${esc(quiz.topic)}</span><span>Question ${index + 1} of ${quiz.questions.length} · ${answered} answered</span></div>
    <div class="bar"><i style="width:${(100 * (index + 1)) / quiz.questions.length}%"></i></div>
    <p class="q-text">${esc(q.question)}</p>
    <div class="opts">${q.options.map((o, oi) => `
      <button class="opt ${answers[index] === oi ? "selected" : ""}" data-opt="${oi}"><span class="key">${LETTERS[oi]}</span><span>${esc(o)}</span></button>`).join("")}</div>
    <div class="quiz-nav">
      <button id="q-prev" ${index === 0 ? "disabled" : ""}>Back</button>
      <div class="dots">${quiz.questions.map((_, i) => `<button data-jump="${i}" class="${i === index ? "current" : ""} ${answers[i] != null ? "answered" : ""}">${i + 1}</button>`).join("")}</div>
      ${last ? `<button class="primary" id="q-submit">Submit</button>` : `<button class="primary" id="q-next">Next</button>`}
    </div>`;

  const go = (i) => { quizState.index = i; saveQuizState(); renderQuiz(); };
  $$("#quiz [data-opt]").forEach((b) => b.addEventListener("click", () => {
    quizState.answers[index] = Number(b.dataset.opt);
    saveQuizState();
    renderQuiz();
  }));
  $$("#quiz [data-jump]").forEach((b) => b.addEventListener("click", () => go(Number(b.dataset.jump))));
  $("#q-prev").addEventListener("click", () => go(index - 1));
  $("#q-next")?.addEventListener("click", () => go(index + 1));
  $("#q-submit")?.addEventListener("click", (e) => {
    const skipped = answers.filter((a) => a == null).length;
    if (skipped && !confirm(`${skipped} question${skipped > 1 ? "s" : ""} unanswered. Submit anyway?`)) return;
    busy(e.target, "Grading…", async () => {
      quizResult = await api(`/api/quiz/${quiz.id}/submit`, { answers });
      quiz = quizState = null;
      saveQuizState();
      await loadProgress();
      renderQuiz();
      renderRoadmap();
    });
  });
}

// Keyboard: 1-4 / A-D pick an option, arrows move, Enter advances.
document.addEventListener("keydown", (e) => {
  if (!quiz || ui.view !== "practice" || ui.tab !== "quiz") return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  const k = e.key.toUpperCase();
  const pick = "1234".indexOf(k) >= 0 ? "1234".indexOf(k) : LETTERS.indexOf(k);
  if (pick >= 0) $(`#quiz [data-opt="${pick}"]`)?.click();
  else if (e.key === "ArrowRight" || e.key === "Enter") ($("#q-next") || (e.key === "Enter" && $("#q-submit")))?.click();
  else if (e.key === "ArrowLeft") $("#q-prev")?.click();
  else return;
  e.preventDefault();
});

// ---------- Code ----------
function renderProblem() {
  const p = problem;
  if (!p) return;
  $("#problem").innerHTML = `
    <span class="badge">${esc(p.difficulty)}</span>
    <h2>${esc(p.title)}</h2>
    <div class="prose">${md(p.statement)}</div>
    ${(p.examples || []).map((e, i) => `
      <h3>Example ${i + 1}</h3>
      <div class="example">Input: ${esc(e.input)}\nOutput: ${esc(e.output)}${e.explanation ? `\n\n${esc(e.explanation)}` : ""}</div>`).join("")}
    ${p.constraints?.length ? `<h3>Constraints</h3><ul>${p.constraints.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}`;
}

function renderReview(r) {
  const cls = r.verdict === "correct" ? "correct" : r.verdict === "incorrect" ? "incorrect" : "partial";
  $("#review-out").innerHTML = `
    <div class="card review">
      <div class="review-head">
        <span class="verdict-pill ${cls}">${esc(r.verdict)}</span>
        <span class="score">${esc(r.score)}/10</span>
      </div>
      <p class="review-summary">${esc(r.summary)}</p>
      <div class="review-grid">
        <div><b>Time complexity</b>${esc(r.timeComplexity)}</div>
        <div><b>Space complexity</b>${esc(r.spaceComplexity)}</div>
      </div>
      ${r.issues?.length ? `<h2>Issues</h2><ul>${r.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
      ${r.betterApproach ? `<h2>Better approach</h2><div class="prose">${md(r.betterApproach)}</div>` : ""}
    </div>`;
  $("#review-out").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#new-problem").addEventListener("click", (e) => {
  const t = currentTopic();
  if (!t) return toast("Generate a roadmap first.");
  const difficulty = document.querySelector("input[name=difficulty]:checked").value;
  busy(e.target, "Generating…", async () => {
    problem = await api("/api/problem", { topic: t.name, difficulty });
    loadEditor();
    renderProblem();
    $("#review-out").innerHTML = "";
  });
});

$("#review").addEventListener("click", (e) => {
  const code = editor.getValue().trim();
  if (!code) return toast("Write some code first.");
  if (!problem) return toast("Generate a problem first.");
  busy(e.target, "Reviewing (up to 30s)…", async () => {
    renderReview(await api("/api/review", { problem_id: problem.id, language: ui.language, code }));
    loadProgress();
  });
});

// ---------- Interview ----------
function renderChat() {
  if (!interview) return;
  const { messages, finished, score } = interview;
  $("#chat").innerHTML = messages.map((m, i) => {
    const verdict = finished && i === messages.length - 1;
    return `<div class="msg ${m.role} ${verdict ? "verdict" : ""}">
      <div class="who-label">${m.role === "assistant" ? (verdict ? "Verdict" : "Interviewer") : "You"}</div>
      ${verdict && score != null ? `<div class="verdict-score">${score}/10</div>` : ""}
      <div class="prose">${m.role === "assistant" ? md(m.content) : esc(m.content)}</div>
    </div>`;
  }).join("");
  $("#answer-form").hidden = finished;
}

$("#start").addEventListener("click", (e) => {
  if (interview && !interview.finished && !confirm("Abandon the current interview and start a new one?")) return;
  busy(e.target, "Starting…", async () => {
    interview = await api("/api/interview", { company: $("#company").value, kind: $("#kind").value, topic: currentTopic()?.name });
    Object.assign(interview, { company: $("#company").value, kind: $("#kind").value });
    renderChat();
    $("#answer").focus();
  });
});

$("#answer-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const answer = $("#answer").value.trim();
  if (!answer) return;
  busy(e.submitter, "Sending…", async () => {
    Object.assign(interview, await api(`/api/interview/${interview.id}/reply`, { answer }));
    $("#answer").value = "";
    renderChat();
    $("#chat").lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (interview.finished) loadProgress();
  });
});
$("#answer").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#answer-form").requestSubmit();
});

// ---------- Profile ----------
function renderProfile() {
  const f = $("#profile-form");
  const p = profile?.profile || {};
  f.name.value = p.name || "";
  f.target_role.value = p.targetRole || "";
  f.target_companies.value = (p.targetCompanies || []).join(", ");
  f.college.value = p.college || "";
  f.year.value = p.year || "";
  f.querySelector(`[name=comfort_level][value="${p.comfortLevel || "Intermediate"}"]`).checked = true;
  f.resume.value = "";
  $("#profile-title").textContent = profile ? "Your profile" : "Welcome! Set up your profile";
  $("#profile-submit").textContent = profile ? "Update profile" : "Save and build my roadmap";
  $("#nav").style.visibility = profile ? "" : "hidden";

  const r = profile?.resume;
  $("#resume-summary").innerHTML = r ? `
    <div class="card">
      <h2>Resume ${r.source === "sarvam-vision" ? `<span class="badge">Read with Sarvam Vision</span>` : ""}</h2>
      <div class="chips">${(r.skills || []).map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>
      ${(r.projects || []).map((pr) => `<div class="resume-item"><strong>${esc(pr.name)}</strong><p>${esc(pr.description)}</p></div>`).join("")}
      ${(r.experience || []).map((x) => `<div class="resume-item"><strong>${esc(x.role)}, ${esc(x.org)}</strong><p>${esc(x.summary)}</p></div>`).join("")}
    </div>` : `<div class="card"><h2>Resume</h2><div class="empty">Upload a PDF resume so quizzes and interview questions reference your real projects. Scanned PDFs work too.</div></div>`;
}

$("#profile-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const hasResume = form.get("resume")?.size > 0;
  if (!hasResume) form.delete("resume");
  const first = !profile;
  busy(e.submitter, hasResume ? "Analyzing resume…" : "Saving…", async () => {
    const res = await api("/api/profile", form, { form: true, method: "PUT" });
    profile = res;
    renderAll();
    toast(res.warning || (first ? "Profile saved. Building your roadmap…" : "Profile updated."));
    if (first) {
      show("roadmap");
      $("#gen-roadmap").click();
    }
  });
});

$("#gen-roadmap").addEventListener("click", (e) => {
  if (profile?.roadmap && !confirm("Regenerate the roadmap? Topic completion will reset.")) return;
  busy(e.target, "Generating…", async () => {
    const res = await api("/api/roadmap", {});
    profile.roadmap = res.roadmap;
    profile.completed_topics = res.completed_topics;
    ui.topic = null;
  }).then(renderAll); // after busy() restores the button, so the label reflects the new state
});

// ---------- Boot ----------
function renderAll() {
  renderShell();
  renderProfile();
  renderRoadmap();
  renderPractice();
  renderProblem();
  renderChat();
  if (ui.view === "home") renderHome();
}

async function boot() {
  $("#boot").hidden = true;
  if (!session) {
    $("#auth").hidden = false;
    return;
  }
  let me;
  try {
    me = await api("/api/me");
  } catch (e) {
    if (e.message !== "Session expired") { $("#auth").hidden = false; toast(e.message); }
    return;
  }
  user = me.user;
  profile = me.profile;
  const r = me.resume || {};
  quiz = r.quiz || null;
  const savedQuiz = local.get("quizState", null);
  quizState = quiz ? (savedQuiz?.id === quiz.id ? { index: savedQuiz.index, answers: savedQuiz.answers } : { index: 0, answers: quiz.questions.map(() => null) }) : null;
  problem = r.problem || null;
  interview = r.interview || null;
  if (quiz) ui.topic = ui.topic || quiz.topic;

  $("#auth").hidden = true;
  $("#app").hidden = false;
  if (profile) await loadProgress();
  renderAll();
  loadEditor();
  showTab(ui.tab);
  show(profile ? ui.view : "profile");
}

boot();

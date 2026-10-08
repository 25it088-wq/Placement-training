"""Placement Trainer: FastAPI web app for aptitude practice, daily tests,
mock interviews, career planning and ML performance analysis.

Run:  python3 app.py            (or: uvicorn app:app --host 0.0.0.0 --port 5000)
"""
import os
import sqlite3
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash

import career
import daily
import interview
import ml
from api import public_router as api_public_router, router as api_router
from db import db_scope, get_db, init_db

BASE_DIR = Path(__file__).resolve().parent
CATEGORIES = ["Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"]
SECONDS_PER_QUESTION = 60

app = FastAPI(title="Placement Trainer")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "dev-only-change-me"))
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(api_public_router)
app.include_router(api_router)


# ---------- request plumbing ----------

@app.middleware("http")
async def database_per_request(request: Request, call_next):
    """One database connection per request, closed when the response is ready."""
    with db_scope():
        return await call_next(request)


class Redirect(Exception):
    """Raised by login and role checks to send the visitor to another page."""

    def __init__(self, url):
        self.url = url


@app.exception_handler(Redirect)
async def _redirect(request: Request, exc: Redirect):
    return RedirectResponse(exc.url, status_code=302)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)
    return await http_exception_handler(request, exc)


def redirect(url):
    return RedirectResponse(url, status_code=302)


def url_for(name, **params):
    """Build a URL by route name. Accepts Flask-style filename= for static files."""
    if name == "static" and "filename" in params:
        params["path"] = params.pop("filename")
    return str(app.url_path_for(name, **params))


_templates = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def render(request, template, **context):
    """Render a page. Adds the signed-in user (me) and any pending flash messages."""
    messages = request.session.pop("_flashes", [])
    context.update(me=current_user(request), url_for=url_for, get_flashed_messages=lambda: messages)
    return HTMLResponse(_templates.get_template(template).render(**context))


def flash(request, message):
    request.session.setdefault("_flashes", []).append(message)


def form_int(form, key):
    """An integer form field, or None when it is missing or not a number."""
    try:
        return int(form.get(key))
    except (TypeError, ValueError):
        return None


# ---------- auth helpers ----------

def current_user(request: Request):
    if not hasattr(request.state, "user"):
        uid = request.session.get("user_id")
        request.state.user = (get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
                              if uid else None)
    return request.state.user


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise Redirect(url_for("login"))
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403)
    return user


def own_session(db, session_id, user):
    """Load an interview session that belongs to the user (admins can view any)."""
    s = db.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    if not s or (s["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404)
    return s


# ---------- public routes ----------

@app.get("/")
def index(request: Request):
    return redirect(url_for("dashboard") if current_user(request) else url_for("login"))


@app.api_route("/register", methods=["GET", "POST"])
async def register(request: Request):
    if request.method == "POST":
        f = await request.form()
        name = str(f.get("name", "")).strip()
        email = str(f.get("email", "")).strip().lower()
        password = str(f.get("password", ""))
        if not name or not email or len(password) < 6:
            flash(request, "Please fill in all fields. The password must be at least 6 characters.")
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)))
                db.commit()
                request.session.clear()
                request.session["user_id"] = cur.lastrowid
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash(request, "An account with this email already exists.")
    return render(request, "auth.html", mode="register")


@app.api_route("/login", methods=["GET", "POST"])
async def login(request: Request):
    if request.method == "POST":
        f = await request.form()
        email = str(f.get("email", "")).strip().lower()
        password = str(f.get("password", ""))
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            request.session.clear()
            request.session["user_id"] = user["id"]
            return redirect(url_for("admin") if user["role"] == "admin" else url_for("dashboard"))
        flash(request, "Invalid email or password.")
    return render(request, "auth.html", mode="login")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect(url_for("login"))


# ---------- student dashboard ----------

@app.get("/dashboard")
def dashboard(request: Request, user=Depends(require_user)):
    db = get_db()
    attempts = db.execute(
        "SELECT * FROM attempts WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 10",
        (user["id"],)).fetchall()
    stats = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(AVG(100.0 * score / total), 0) AS avg "
        "FROM attempts WHERE user_id = ?", (user["id"],)).fetchone()
    bank = {r["category"]: r["n"] for r in db.execute(
        "SELECT category, COUNT(*) AS n FROM questions GROUP BY category")}
    analysis = ml.analyze_user(db, user["id"])

    today = daily.today()
    interviews = interview.sessions_summary(db, user["id"])
    avgs = [r["avg_score"] for r in interviews if r["avg_score"] is not None]
    return render(
        request, "dashboard.html",
        attempts=attempts, stats=stats, analysis=analysis, categories=CATEGORIES, bank=bank,
        daily_done=daily.completed(db, user["id"], today) is not None,
        streak=daily.streak(db, user["id"], today), daily_count=daily.DAILY_COUNT,
        interviews=interviews,
        interview_avg=round(sum(avgs) / len(avgs), 1) if avgs else None)


# ---------- practice quiz ----------

@app.post("/quiz/start")
async def quiz_start(request: Request, user=Depends(require_user)):
    f = await request.form()
    category = str(f.get("category", "Mixed"))
    try:
        count = max(5, min(20, int(f.get("count", 10))))
    except ValueError:
        count = 10

    db = get_db()
    if category == "Mixed":
        rows = db.execute("SELECT id FROM questions ORDER BY RANDOM() LIMIT ?", (count,)).fetchall()
    else:
        rows = db.execute(
            "SELECT id FROM questions WHERE category = ? ORDER BY RANDOM() LIMIT ?",
            (category, count)).fetchall()

    if not rows:
        flash(request, "No questions are available for that category yet.")
        return redirect(url_for("dashboard"))

    request.session["quiz"] = {
        "ids": [r["id"] for r in rows],
        "category": category,
        "started": time.time(),
    }
    return redirect(url_for("quiz"))


@app.get("/quiz")
def quiz(request: Request, user=Depends(require_user)):
    qz = request.session.get("quiz")
    if not qz:
        return redirect(url_for("dashboard"))
    db = get_db()
    placeholders = ",".join("?" * len(qz["ids"]))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", qz["ids"]).fetchall()
    by_id = {r["id"]: r for r in rows}
    questions = [by_id[i] for i in qz["ids"] if i in by_id]
    limit = SECONDS_PER_QUESTION * len(questions)
    remaining = max(0, int(limit - (time.time() - qz["started"])))
    return render(request, "quiz.html", questions=questions, category=qz["category"], limit=remaining)


@app.post("/quiz/submit")
async def quiz_submit(request: Request, user=Depends(require_user)):
    qz = request.session.pop("quiz", None)
    if not qz:
        return redirect(url_for("dashboard"))

    f = await request.form()
    db = get_db()
    elapsed = int(time.time() - qz["started"])
    placeholders = ",".join("?" * len(qz["ids"]))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", qz["ids"]).fetchall()
    if not rows:
        return redirect(url_for("dashboard"))

    score = 0
    answers = []
    for r in rows:
        raw = f.get(f"q{r['id']}")
        selected = int(raw) if raw in ("0", "1", "2", "3") else None
        correct = 1 if selected == r["answer"] else 0
        score += correct
        answers.append((r["id"], r["category"], r["difficulty"], selected, correct))

    cur = db.execute(
        "INSERT INTO attempts (user_id, category, score, total, time_taken) VALUES (?, ?, ?, ?, ?)",
        (user["id"], qz["category"], score, len(rows), elapsed))
    attempt_id = cur.lastrowid
    db.executemany(
        """INSERT INTO attempt_answers
           (attempt_id, user_id, question_id, category, difficulty, selected, is_correct)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(attempt_id, user["id"], qid, cat, diff, sel, cor) for qid, cat, diff, sel, cor in answers])

    if qz.get("daily"):
        try:
            db.execute("INSERT INTO daily_tests (user_id, test_date, attempt_id) VALUES (?, ?, ?)",
                       (user["id"], qz["daily"], attempt_id))
        except sqlite3.IntegrityError:
            pass  # already recorded for today; the attempt itself is still saved
    db.commit()
    return redirect(url_for("result", attempt_id=attempt_id))


@app.get("/result/{attempt_id}")
def result(attempt_id: int, request: Request, user=Depends(require_user)):
    db = get_db()
    attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt or (attempt["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404)
    rows = db.execute(
        """SELECT aa.*, q.text, q.option_a, q.option_b, q.option_c, q.option_d,
                  q.answer, q.explanation
           FROM attempt_answers aa JOIN questions q ON q.id = aa.question_id
           WHERE aa.attempt_id = ? ORDER BY aa.id""", (attempt_id,)).fetchall()
    return render(request, "result.html", attempt=attempt, rows=rows)


@app.get("/analysis")
def analysis(request: Request, user=Depends(require_user)):
    result_data = ml.analyze_user(get_db(), user["id"])
    return render(request, "analysis.html", a=result_data)


# ---------- daily test ----------

@app.get("/daily")
def daily_page(request: Request, user=Depends(require_user)):
    db = get_db()
    day = daily.today()
    analysis_data = ml.analyze_user(db, user["id"])
    return render(
        request, "daily.html",
        day=day,
        done=daily.completed(db, user["id"], day),
        focus=daily.focus_order(analysis_data),
        streak=daily.streak(db, user["id"], day),
        week=daily.history(db, user["id"], day),
        count=daily.DAILY_COUNT,
    )


@app.post("/daily/start")
def daily_start(request: Request, user=Depends(require_user)):
    db = get_db()
    day = daily.today()
    if daily.completed(db, user["id"], day):
        flash(request, "You have already completed today's test. Come back tomorrow for a new set.")
        return redirect(url_for("daily_page"))

    ids = daily.pick_questions(db, user["id"], day)
    if not ids:
        flash(request, "No questions are available yet.")
        return redirect(url_for("daily_page"))

    request.session["quiz"] = {
        "ids": ids,
        "category": "Daily practice",
        "started": time.time(),
        "daily": day.isoformat(),
    }
    return redirect(url_for("quiz"))


# ---------- mock interviews ----------

@app.get("/interview")
def interview_page(request: Request, user=Depends(require_user)):
    db = get_db()
    return render(
        request, "interview.html",
        sessions=interview.sessions_summary(db, user["id"]),
        types=interview.TYPES,
        counts=[3, 5],
    )


@app.post("/interview/start")
async def interview_start(request: Request, user=Depends(require_user)):
    db = get_db()
    f = await request.form()
    itype = str(f.get("type", "Mixed"))
    if itype != "Mixed" and itype not in interview.TYPES:
        itype = "Mixed"
    try:
        count = max(3, min(5, int(f.get("count", 3))))
    except ValueError:
        count = 3

    qids = interview.pick_questions(db, itype, count)
    if not qids:
        flash(request, "No interview questions are available for that type.")
        return redirect(url_for("interview_page"))

    cur = db.execute("INSERT INTO interview_sessions (user_id, interview_type) VALUES (?, ?)",
                     (user["id"], itype))
    sid = cur.lastrowid
    db.executemany(
        "INSERT INTO interview_items (session_id, position, question_id) VALUES (?, ?, ?)",
        [(sid, i + 1, q) for i, q in enumerate(qids)])
    db.commit()
    return redirect(url_for("interview_session", session_id=sid))


@app.get("/interview/{session_id}")
def interview_session(session_id: int, request: Request, user=Depends(require_user)):
    db = get_db()
    s = own_session(db, session_id, user)
    item = db.execute(
        """SELECT i.id, i.position, q.text AS question, q.interview_type
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.session_id = ? AND i.answer IS NULL
           ORDER BY i.position LIMIT 1""", (session_id,)).fetchone()
    if item is None:
        return redirect(url_for("interview_report", session_id=session_id))
    total = db.execute("SELECT COUNT(*) FROM interview_items WHERE session_id = ?",
                       (session_id,)).fetchone()[0]
    return render(
        request, "interview_session.html",
        s=s, item=item, number=item["position"], total=total,
        limit=interview.SECONDS_PER_ANSWER,
        tip=interview.TIPS[item["interview_type"]],
    )


@app.post("/interview/{session_id}/answer")
async def interview_answer(session_id: int, request: Request, user=Depends(require_user)):
    db = get_db()
    own_session(db, session_id, user)
    f = await request.form()
    item_id = form_int(f, "item_id")
    item = db.execute(
        """SELECT i.id, q.interview_type, q.keywords
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.id = ? AND i.session_id = ? AND i.answer IS NULL""",
        (item_id, session_id)).fetchone()
    if item:
        text = str(f.get("answer", "")).strip()[:4000]
        res = interview.score_answer(text, item["interview_type"], item["keywords"])
        db.execute(
            """UPDATE interview_items
               SET answer = ?, score = ?, word_count = ?, filler_count = ?, answered_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (text, res["score"], res["words"], res["filler_count"], item["id"]))
        db.commit()
    return redirect(url_for("interview_session", session_id=session_id))


@app.get("/interview/{session_id}/report")
def interview_report(session_id: int, request: Request, user=Depends(require_user)):
    db = get_db()
    s = own_session(db, session_id, user)
    rows = db.execute(
        """SELECT i.*, q.text AS question, q.keywords, q.interview_type
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.session_id = ? ORDER BY i.position""", (session_id,)).fetchall()
    if not rows or any(r["answer"] is None for r in rows):
        return redirect(url_for("interview_session", session_id=session_id))

    items = [{"row": r,
              "res": interview.score_answer(r["answer"], r["interview_type"], r["keywords"])}
             for r in rows]
    avg = round(sum(r["score"] for r in rows) / len(rows), 1)
    return render(request, "interview_report.html", s=s, items=items, avg=avg,
                  label=interview.label(avg))


# ---------- admin ----------

@app.get("/admin")
def admin(request: Request, user=Depends(require_admin)):
    db = get_db()
    students = db.execute(
        "SELECT id, name, email, created_at FROM users WHERE role = 'student' ORDER BY name").fetchall()
    rows = []
    for s in students:
        n = db.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (s["id"],)).fetchone()[0]
        rows.append({"student": s, "attempts": n, "analysis": ml.analyze_user(db, s["id"])})
    bank = db.execute("SELECT category, COUNT(*) AS n FROM questions GROUP BY category ORDER BY category").fetchall()
    return render(request, "admin.html", rows=rows, bank=bank, cohort=ml.cohort_summary(db))


@app.api_route("/admin/questions/new", methods=["GET", "POST"])
async def admin_new_question(request: Request, user=Depends(require_admin)):
    if request.method == "POST":
        f = await request.form()
        category = str(f.get("category", "")).strip()
        text = str(f.get("text", "")).strip()
        opts = [str(f.get(k, "")).strip() for k in ("option_a", "option_b", "option_c", "option_d")]
        explanation = str(f.get("explanation", "")).strip()
        try:
            answer = int(f.get("answer", -1))
            difficulty = max(1, min(3, int(f.get("difficulty", 1))))
        except ValueError:
            answer, difficulty = -1, 1
        if not category or not text or not all(opts) or answer not in (0, 1, 2, 3):
            flash(request, "Please fill in every field and choose the correct option.")
        else:
            db = get_db()
            db.execute(
                """INSERT INTO questions
                   (category, difficulty, text, option_a, option_b, option_c, option_d, answer, explanation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (category, difficulty, text, *opts, answer, explanation))
            db.commit()
            flash(request, "Question added.")
            return redirect(url_for("admin"))
    return render(request, "admin_new_question.html", categories=CATEGORIES)


# ---------- career: target role, company and readiness ----------

@app.get("/career")
def career_page(request: Request, user=Depends(require_user)):
    db = get_db()
    target = career.get_target(db, user["id"])
    readiness_data = topics = questions = alumni = company = company_name = None
    if target:
        company_name = career.target_company_name(target)
        readiness_data = career.readiness(db, user["id"], target)
        topics = career.role_topics(db, target["role_id"])
        if target["company_id"]:
            company = db.execute("SELECT * FROM companies WHERE id = ?", (target["company_id"],)).fetchone()
            questions = career.company_questions(db, target["company_id"])
            alumni = career.public_alumni(db, target["company_id"])
    return render(
        request, "career.html",
        target=target, company=company, company_name=company_name,
        readiness=readiness_data, topics=topics, questions=questions, alumni=alumni,
        roles=db.execute("SELECT id, title FROM job_roles ORDER BY title").fetchall(),
        companies=db.execute("SELECT id, name FROM companies ORDER BY name").fetchall(),
    )


@app.post("/career/target")
async def career_target_save(request: Request, user=Depends(require_user)):
    db = get_db()
    f = await request.form()
    role_id = form_int(f, "role_id")
    if role_id is None:
        flash(request, "Choose a job role.")
        return redirect(url_for("career_page"))
    company_id = None
    if f.get("company_id"):
        company_id = form_int(f, "company_id")
        if company_id is None:
            company_id = -1  # invalid id; save_target will reject it
    position = str(f.get("position_title", "")).strip()
    if not position:
        flash(request, "Enter the position you want, for example Associate Software Engineer.")
        return redirect(url_for("career_page"))
    ok, err = career.save_target(db, user["id"], role_id, company_id=company_id,
                                 company_name=str(f.get("company_name", "")), position_title=position)
    flash(request, "Career target saved." if ok else err)
    return redirect(url_for("career_page"))


@app.api_route("/career/alumni", methods=["GET", "POST"])
async def alumni_join(request: Request, user=Depends(require_user)):
    db = get_db()
    if request.method == "POST":
        f = await request.form()
        if f.get("action") == "remove":
            career.remove_alumni(db, user["id"])
            flash(request, "Your profile was removed from the alumni directory.")
            return redirect(url_for("career_page"))
        company_id = None
        if f.get("company_id"):
            company_id = form_int(f, "company_id")
            if company_id is None:
                company_id = -1
        ok, err = career.save_alumni(
            db, user["id"], company_id, str(f.get("company_name", "")), str(f.get("role_title", "")),
            batch_year=str(f.get("batch_year", "")), phone=str(f.get("phone", "")),
            public_email=str(f.get("public_email", "")), consent=f.get("consent") == "on")
        if ok:
            flash(request, "Thanks. Your profile appears in the directory once the placement cell verifies it.")
            return redirect(url_for("career_page"))
        flash(request, err)
    existing = db.execute("SELECT * FROM alumni_profiles WHERE user_id = ?", (user["id"],)).fetchone()
    companies = db.execute("SELECT id, name FROM companies ORDER BY name").fetchall()
    return render(request, "career_alumni.html", existing=existing, companies=companies)


# ---------- admin: career ----------

@app.get("/admin/career")
def admin_career(request: Request, user=Depends(require_admin)):
    db = get_db()
    companies = db.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM company_questions q WHERE q.company_id = c.id) AS qcount,
               (SELECT COUNT(*) FROM alumni_profiles a WHERE a.company_id = c.id AND a.verified = 1) AS alumni_count
        FROM companies c ORDER BY c.name""").fetchall()
    pending = db.execute("""
        SELECT a.*, u.name, u.email FROM alumni_profiles a JOIN users u ON u.id = a.user_id
        ORDER BY a.verified ASC, a.created_at DESC""").fetchall()
    return render(request, "admin_career.html", companies=companies, pending=pending,
                  round_types=career.ROUND_ORDER)


@app.post("/admin/companies/new")
async def admin_company_new(request: Request, user=Depends(require_admin)):
    f = await request.form()
    name = str(f.get("name", "")).strip()[:100]
    if not name:
        flash(request, "Enter a company name.")
        return redirect(url_for("admin_career"))
    db = get_db()
    try:
        db.execute("INSERT INTO companies (name, sector, hiring_process) VALUES (?, ?, ?)",
                   (name, str(f.get("sector", "")).strip()[:100],
                    str(f.get("hiring_process", "")).strip()[:1000]))
        db.commit()
        flash(request, "Company added.")
    except sqlite3.IntegrityError:
        flash(request, "A company with that name already exists.")
    return redirect(url_for("admin_career"))


@app.post("/admin/company-questions/new")
async def admin_company_question_new(request: Request, user=Depends(require_admin)):
    f = await request.form()
    company_id = form_int(f, "company_id")
    if company_id is None:
        flash(request, "Choose a company.")
        return redirect(url_for("admin_career"))
    round_type = str(f.get("round_type", ""))
    question = str(f.get("question", "")).strip()[:500]
    if round_type not in career.ROUND_ORDER or not question:
        flash(request, "Choose a round and enter the question.")
        return redirect(url_for("admin_career"))
    source_url = str(f.get("source_url", "")).strip()[:300]
    if source_url and not source_url.startswith(("http://", "https://")):
        source_url = ""  # keep only real web links
    db = get_db()
    if db.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone() is None:
        flash(request, "Choose a valid company.")
        return redirect(url_for("admin_career"))
    db.execute(
        """INSERT INTO company_questions (company_id, round_type, question, year, source_url, source_note)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (company_id, round_type, question, str(f.get("year", "")).strip()[:4],
         source_url, str(f.get("source_note", "")).strip()[:300]))
    db.commit()
    flash(request, "Question added.")
    return redirect(url_for("admin_career"))


@app.post("/admin/alumni/{alumni_id}/verify")
def admin_alumni_verify(alumni_id: int, request: Request, user=Depends(require_admin)):
    db = get_db()
    db.execute("UPDATE alumni_profiles SET verified = 1 WHERE id = ?", (alumni_id,))
    db.commit()
    flash(request, "Alumni profile verified and listed.")
    return redirect(url_for("admin_career"))


@app.post("/admin/alumni/{alumni_id}/remove")
def admin_alumni_remove(alumni_id: int, request: Request, user=Depends(require_admin)):
    db = get_db()
    db.execute("DELETE FROM alumni_profiles WHERE id = ?", (alumni_id,))
    db.commit()
    flash(request, "Alumni profile removed.")
    return redirect(url_for("admin_career"))


init_db()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)

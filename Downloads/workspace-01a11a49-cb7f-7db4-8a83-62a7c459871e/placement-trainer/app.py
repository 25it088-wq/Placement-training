"""Placement Trainer: Flask web app for aptitude practice, daily tests,
mock interviews and ML performance analysis."""
import os
import sqlite3
import time
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import career
import daily
import interview
import ml
from api import api
from db import close_db, get_db, init_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.teardown_appcontext(close_db)
app.register_blueprint(api)

CATEGORIES = ["Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"]
SECONDS_PER_QUESTION = 60


# ---------- auth helpers ----------

def current_user():
    if "user" not in g:
        uid = session.get("user_id")
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
    return g.user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def own_session(db, session_id, user):
    """Load an interview session that belongs to the user (admins can view any)."""
    s = db.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    if not s or (s["user_id"] != user["id"] and user["role"] != "admin"):
        abort(404)
    return s


@app.context_processor
def inject_user():
    return {"me": current_user()}


# ---------- public routes ----------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Please fill in all fields. The password must be at least 6 characters.")
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)))
                db.commit()
                session.clear()
                session["user_id"] = cur.lastrowid
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("An account with this email already exists.")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("admin") if user["role"] == "admin" else url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- student dashboard ----------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user = current_user()
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
    return render_template(
        "dashboard.html",
        attempts=attempts, stats=stats, analysis=analysis, categories=CATEGORIES, bank=bank,
        daily_done=daily.completed(db, user["id"], today) is not None,
        streak=daily.streak(db, user["id"], today), daily_count=daily.DAILY_COUNT,
        interviews=interviews,
        interview_avg=round(sum(avgs) / len(avgs), 1) if avgs else None)


# ---------- practice quiz ----------

@app.route("/quiz/start", methods=["POST"])
@login_required
def quiz_start():
    category = request.form.get("category", "Mixed")
    try:
        count = max(5, min(20, int(request.form.get("count", 10))))
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
        flash("No questions are available for that category yet.")
        return redirect(url_for("dashboard"))

    session["quiz"] = {
        "ids": [r["id"] for r in rows],
        "category": category,
        "started": time.time(),
    }
    return redirect(url_for("quiz"))


@app.route("/quiz")
@login_required
def quiz():
    qz = session.get("quiz")
    if not qz:
        return redirect(url_for("dashboard"))
    db = get_db()
    placeholders = ",".join("?" * len(qz["ids"]))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", qz["ids"]).fetchall()
    by_id = {r["id"]: r for r in rows}
    questions = [by_id[i] for i in qz["ids"] if i in by_id]
    limit = SECONDS_PER_QUESTION * len(questions)
    remaining = max(0, int(limit - (time.time() - qz["started"])))
    return render_template("quiz.html", questions=questions, category=qz["category"], limit=remaining)


@app.route("/quiz/submit", methods=["POST"])
@login_required
def quiz_submit():
    qz = session.pop("quiz", None)
    if not qz:
        return redirect(url_for("dashboard"))

    user = current_user()
    db = get_db()
    elapsed = int(time.time() - qz["started"])
    placeholders = ",".join("?" * len(qz["ids"]))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", qz["ids"]).fetchall()
    if not rows:
        return redirect(url_for("dashboard"))

    score = 0
    answers = []
    for r in rows:
        raw = request.form.get(f"q{r['id']}")
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


@app.route("/result/<int:attempt_id>")
@login_required
def result(attempt_id):
    db = get_db()
    user = current_user()
    attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt or (attempt["user_id"] != user["id"] and user["role"] != "admin"):
        abort(404)
    rows = db.execute(
        """SELECT aa.*, q.text, q.option_a, q.option_b, q.option_c, q.option_d,
                  q.answer, q.explanation
           FROM attempt_answers aa JOIN questions q ON q.id = aa.question_id
           WHERE aa.attempt_id = ? ORDER BY aa.id""", (attempt_id,)).fetchall()
    return render_template("result.html", attempt=attempt, rows=rows)


@app.route("/analysis")
@login_required
def analysis():
    user = current_user()
    result_data = ml.analyze_user(get_db(), user["id"])
    return render_template("analysis.html", a=result_data)


# ---------- daily test ----------

@app.route("/daily")
@login_required
def daily_page():
    db = get_db()
    user = current_user()
    day = daily.today()
    analysis_data = ml.analyze_user(db, user["id"])
    return render_template(
        "daily.html",
        day=day,
        done=daily.completed(db, user["id"], day),
        focus=daily.focus_order(analysis_data),
        streak=daily.streak(db, user["id"], day),
        week=daily.history(db, user["id"], day),
        count=daily.DAILY_COUNT,
    )


@app.route("/daily/start", methods=["POST"])
@login_required
def daily_start():
    db = get_db()
    user = current_user()
    day = daily.today()
    if daily.completed(db, user["id"], day):
        flash("You have already completed today's test. Come back tomorrow for a new set.")
        return redirect(url_for("daily_page"))

    ids = daily.pick_questions(db, user["id"], day)
    if not ids:
        flash("No questions are available yet.")
        return redirect(url_for("daily_page"))

    session["quiz"] = {
        "ids": ids,
        "category": "Daily practice",
        "started": time.time(),
        "daily": day.isoformat(),
    }
    return redirect(url_for("quiz"))


# ---------- mock interviews ----------

@app.route("/interview")
@login_required
def interview_page():
    db = get_db()
    user = current_user()
    return render_template(
        "interview.html",
        sessions=interview.sessions_summary(db, user["id"]),
        types=interview.TYPES,
        counts=[3, 5],
    )


@app.route("/interview/start", methods=["POST"])
@login_required
def interview_start():
    db = get_db()
    user = current_user()
    itype = request.form.get("type", "Mixed")
    if itype != "Mixed" and itype not in interview.TYPES:
        itype = "Mixed"
    try:
        count = max(3, min(5, int(request.form.get("count", 3))))
    except ValueError:
        count = 3

    qids = interview.pick_questions(db, itype, count)
    if not qids:
        flash("No interview questions are available for that type.")
        return redirect(url_for("interview_page"))

    cur = db.execute("INSERT INTO interview_sessions (user_id, interview_type) VALUES (?, ?)",
                     (user["id"], itype))
    sid = cur.lastrowid
    db.executemany(
        "INSERT INTO interview_items (session_id, position, question_id) VALUES (?, ?, ?)",
        [(sid, i + 1, q) for i, q in enumerate(qids)])
    db.commit()
    return redirect(url_for("interview_session", session_id=sid))


@app.route("/interview/<int:session_id>")
@login_required
def interview_session(session_id):
    db = get_db()
    user = current_user()
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
    return render_template(
        "interview_session.html",
        s=s, item=item, number=item["position"], total=total,
        limit=interview.SECONDS_PER_ANSWER,
        tip=interview.TIPS[item["interview_type"]],
    )


@app.route("/interview/<int:session_id>/answer", methods=["POST"])
@login_required
def interview_answer(session_id):
    db = get_db()
    user = current_user()
    own_session(db, session_id, user)
    item_id = request.form.get("item_id", type=int)
    item = db.execute(
        """SELECT i.id, q.interview_type, q.keywords
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.id = ? AND i.session_id = ? AND i.answer IS NULL""",
        (item_id, session_id)).fetchone()
    if item:
        text = request.form.get("answer", "").strip()[:4000]
        res = interview.score_answer(text, item["interview_type"], item["keywords"])
        db.execute(
            """UPDATE interview_items
               SET answer = ?, score = ?, word_count = ?, filler_count = ?, answered_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (text, res["score"], res["words"], res["filler_count"], item["id"]))
        db.commit()
    return redirect(url_for("interview_session", session_id=session_id))


@app.route("/interview/<int:session_id>/report")
@login_required
def interview_report(session_id):
    db = get_db()
    user = current_user()
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
    return render_template("interview_report.html", s=s, items=items, avg=avg,
                           label=interview.label(avg))


# ---------- admin ----------

@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    students = db.execute(
        "SELECT id, name, email, created_at FROM users WHERE role = 'student' ORDER BY name").fetchall()
    rows = []
    for s in students:
        n = db.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (s["id"],)).fetchone()[0]
        rows.append({"student": s, "attempts": n, "analysis": ml.analyze_user(db, s["id"])})
    bank = db.execute("SELECT category, COUNT(*) AS n FROM questions GROUP BY category ORDER BY category").fetchall()
    return render_template("admin.html", rows=rows, bank=bank, cohort=ml.cohort_summary(db))


@app.route("/admin/questions/new", methods=["GET", "POST"])
@admin_required
def admin_new_question():
    if request.method == "POST":
        f = request.form
        category = f.get("category", "").strip()
        text = f.get("text", "").strip()
        opts = [f.get(k, "").strip() for k in ("option_a", "option_b", "option_c", "option_d")]
        explanation = f.get("explanation", "").strip()
        try:
            answer = int(f.get("answer", -1))
            difficulty = max(1, min(3, int(f.get("difficulty", 1))))
        except ValueError:
            answer, difficulty = -1, 1
        if not category or not text or not all(opts) or answer not in (0, 1, 2, 3):
            flash("Please fill in every field and choose the correct option.")
        else:
            db = get_db()
            db.execute(
                """INSERT INTO questions
                   (category, difficulty, text, option_a, option_b, option_c, option_d, answer, explanation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (category, difficulty, text, *opts, answer, explanation))
            db.commit()
            flash("Question added.")
            return redirect(url_for("admin"))
    return render_template("admin_new_question.html", categories=CATEGORIES)


# ---------- career: target role, company and readiness ----------

@app.route("/career")
@login_required
def career_page():
    db = get_db()
    user = current_user()
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
    return render_template(
        "career.html",
        target=target, company=company, company_name=company_name,
        readiness=readiness_data, topics=topics, questions=questions, alumni=alumni,
        roles=db.execute("SELECT id, title FROM job_roles ORDER BY title").fetchall(),
        companies=db.execute("SELECT id, name FROM companies ORDER BY name").fetchall(),
    )


@app.route("/career/target", methods=["POST"])
@login_required
def career_target_save():
    db = get_db()
    user = current_user()
    f = request.form
    try:
        role_id = int(f.get("role_id", ""))
    except ValueError:
        flash("Choose a job role.")
        return redirect(url_for("career_page"))
    company_id = None
    if f.get("company_id"):
        try:
            company_id = int(f["company_id"])
        except ValueError:
            company_id = -1  # invalid id; save_target will reject it
    position = f.get("position_title", "").strip()
    if not position:
        flash("Enter the position you want, for example Associate Software Engineer.")
        return redirect(url_for("career_page"))
    ok, err = career.save_target(db, user["id"], role_id, company_id=company_id,
                                 company_name=f.get("company_name", ""), position_title=position)
    flash("Career target saved." if ok else err)
    return redirect(url_for("career_page"))


@app.route("/career/alumni", methods=["GET", "POST"])
@login_required
def alumni_join():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        f = request.form
        if f.get("action") == "remove":
            career.remove_alumni(db, user["id"])
            flash("Your profile was removed from the alumni directory.")
            return redirect(url_for("career_page"))
        company_id = None
        if f.get("company_id"):
            try:
                company_id = int(f["company_id"])
            except ValueError:
                company_id = -1
        ok, err = career.save_alumni(
            db, user["id"], company_id, f.get("company_name", ""), f.get("role_title", ""),
            batch_year=f.get("batch_year", ""), phone=f.get("phone", ""),
            public_email=f.get("public_email", ""), consent=f.get("consent") == "on")
        if ok:
            flash("Thanks. Your profile appears in the directory once the placement cell verifies it.")
            return redirect(url_for("career_page"))
        flash(err)
    existing = db.execute("SELECT * FROM alumni_profiles WHERE user_id = ?", (user["id"],)).fetchone()
    companies = db.execute("SELECT id, name FROM companies ORDER BY name").fetchall()
    return render_template("career_alumni.html", existing=existing, companies=companies)


# ---------- admin: career ----------

@app.route("/admin/career")
@admin_required
def admin_career():
    db = get_db()
    companies = db.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM company_questions q WHERE q.company_id = c.id) AS qcount,
               (SELECT COUNT(*) FROM alumni_profiles a WHERE a.company_id = c.id AND a.verified = 1) AS alumni_count
        FROM companies c ORDER BY c.name""").fetchall()
    pending = db.execute("""
        SELECT a.*, u.name, u.email FROM alumni_profiles a JOIN users u ON u.id = a.user_id
        ORDER BY a.verified ASC, a.created_at DESC""").fetchall()
    return render_template("admin_career.html", companies=companies, pending=pending,
                           round_types=career.ROUND_ORDER)


@app.route("/admin/companies/new", methods=["POST"])
@admin_required
def admin_company_new():
    f = request.form
    name = f.get("name", "").strip()[:100]
    if not name:
        flash("Enter a company name.")
        return redirect(url_for("admin_career"))
    db = get_db()
    try:
        db.execute("INSERT INTO companies (name, sector, hiring_process) VALUES (?, ?, ?)",
                   (name, f.get("sector", "").strip()[:100], f.get("hiring_process", "").strip()[:1000]))
        db.commit()
        flash("Company added.")
    except sqlite3.IntegrityError:
        flash("A company with that name already exists.")
    return redirect(url_for("admin_career"))


@app.route("/admin/company-questions/new", methods=["POST"])
@admin_required
def admin_company_question_new():
    f = request.form
    try:
        company_id = int(f.get("company_id", ""))
    except ValueError:
        flash("Choose a company.")
        return redirect(url_for("admin_career"))
    round_type = f.get("round_type", "")
    question = f.get("question", "").strip()[:500]
    if round_type not in career.ROUND_ORDER or not question:
        flash("Choose a round and enter the question.")
        return redirect(url_for("admin_career"))
    source_url = f.get("source_url", "").strip()[:300]
    if source_url and not source_url.startswith(("http://", "https://")):
        source_url = ""  # keep only real web links
    db = get_db()
    if db.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone() is None:
        flash("Choose a valid company.")
        return redirect(url_for("admin_career"))
    db.execute(
        """INSERT INTO company_questions (company_id, round_type, question, year, source_url, source_note)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (company_id, round_type, question, f.get("year", "").strip()[:4],
         source_url, f.get("source_note", "").strip()[:300]))
    db.commit()
    flash("Question added.")
    return redirect(url_for("admin_career"))


@app.route("/admin/alumni/<int:alumni_id>/verify", methods=["POST"])
@admin_required
def admin_alumni_verify(alumni_id):
    db = get_db()
    db.execute("UPDATE alumni_profiles SET verified = 1 WHERE id = ?", (alumni_id,))
    db.commit()
    flash("Alumni profile verified and listed.")
    return redirect(url_for("admin_career"))


@app.route("/admin/alumni/<int:alumni_id>/remove", methods=["POST"])
@admin_required
def admin_alumni_remove(alumni_id):
    db = get_db()
    db.execute("DELETE FROM alumni_profiles WHERE id = ?", (alumni_id,))
    db.commit()
    flash("Alumni profile removed.")
    return redirect(url_for("admin_career"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

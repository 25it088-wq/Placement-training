"""JSON API for Placement Trainer (v1). Base path: /api/v1

Authentication
    POST /api/v1/auth/login  -> {"token": "...", "user": {...}}
    Send the token on every other request:  Authorization: Bearer <token>
    Tokens are stored as SHA-256 hashes. POST /api/v1/auth/logout revokes one.

All request and response bodies are JSON. Errors look like {"error": "..."}.
See docs/API.md for the full reference.
"""
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from werkzeug.security import check_password_hash

import career
import daily
import interview
import ml
from db import get_db

CATEGORIES = ["Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"]


# ---------- helpers ----------

def jsonify(data, status=200):
    return JSONResponse(data, status_code=status)


def _err(message, status=400):
    return JSONResponse({"error": message}, status_code=status)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _bearer_token(request):
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.startswith("Bearer ") else None


async def _json_body(request):
    """The JSON object sent with the request, or {} if there is none or it is not an object."""
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _body(request):
    """The JSON body parsed once by api_user (available on authenticated routes)."""
    return request.state.body


async def api_user(request: Request):
    """Router-level dependency: check the bearer token and parse the JSON body once."""
    token = _bearer_token(request)
    if not token:
        raise HTTPException(401, "missing bearer token")
    row = get_db().execute(
        """SELECT u.* FROM api_tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token_hash = ?""", (_hash(token),)).fetchone()
    if row is None:
        raise HTTPException(401, "invalid or revoked token")
    request.state.api_user = row
    request.state.body = await _json_body(request)
    return row


# Public routes (no token needed) and authenticated routes.
public_router = APIRouter(prefix="/api/v1")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_user)])


def _user_json(u):
    return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}


def _question_json(r, include_answer=False):
    data = {
        "id": r["id"],
        "category": r["category"],
        "difficulty": r["difficulty"],
        "text": r["text"],
        "options": [r["option_a"], r["option_b"], r["option_c"], r["option_d"]],
    }
    if include_answer:
        data["correct_option"] = r["answer"]
        data["explanation"] = r["explanation"]
    return data


def _questions_by_ids(db, ids):
    if not ids:
        return []
    rows = db.execute(
        f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [_question_json(by_id[i]) for i in ids if i in by_id]


def _parse_answers(payload):
    """Validate [{"question_id": int, "selected": 0-3 or null}, ...]. Returns (list, error)."""
    raw = payload.get("answers")
    if not isinstance(raw, list) or not raw:
        return None, "answers must be a non-empty list"
    parsed, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "each answer must be an object"
        qid, sel = item.get("question_id"), item.get("selected")
        if not isinstance(qid, int) or isinstance(qid, bool):
            return None, "question_id must be an integer"
        if sel is not None and (not isinstance(sel, int) or isinstance(sel, bool) or not 0 <= sel <= 3):
            return None, "selected must be 0 to 3, or null if skipped"
        if qid in seen:
            return None, f"duplicate question_id {qid}"
        seen.add(qid)
        parsed.append((qid, sel))
    return parsed, None


def _record_attempt(db, user_id, category, parsed, time_taken=0, daily_date=None):
    """Grade and store an attempt. Returns (result dict, error)."""
    ids = [qid for qid, _ in parsed]
    rows = db.execute(
        f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [q for q in ids if q not in by_id]
    if missing:
        return None, f"unknown question_id(s): {missing}"

    score, results, records = 0, [], []
    for qid, sel in parsed:
        r = by_id[qid]
        ok = 1 if sel == r["answer"] else 0
        score += ok
        results.append({
            "question_id": qid,
            "selected": sel,
            "correct": bool(ok),
            "correct_option": r["answer"],
            "explanation": r["explanation"],
        })
        records.append((qid, r["category"], r["difficulty"], sel, ok))

    cur = db.execute(
        "INSERT INTO attempts (user_id, category, score, total, time_taken) VALUES (?, ?, ?, ?, ?)",
        (user_id, category, score, len(parsed), time_taken))
    attempt_id = cur.lastrowid
    db.executemany(
        """INSERT INTO attempt_answers
           (attempt_id, user_id, question_id, category, difficulty, selected, is_correct)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(attempt_id, user_id, *rec) for rec in records])
    if daily_date:
        db.execute("INSERT INTO daily_tests (user_id, test_date, attempt_id) VALUES (?, ?, ?)",
                   (user_id, daily_date, attempt_id))
    db.commit()
    return {
        "attempt_id": attempt_id,
        "score": score,
        "total": len(parsed),
        "percent": round(100.0 * score / len(parsed), 1),
        "results": results,
    }, None


def _own_session(db, session_id, user):
    row = db.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None or (row["user_id"] != user["id"] and user["role"] != "admin"):
        return None
    return row


def _item_json(r):
    answered = r["answer"] is not None
    data = {
        "id": r["id"],
        "position": r["position"],
        "interview_type": r["interview_type"],
        "question": r["question"],
        "answered": answered,
    }
    if answered:
        data["score"] = r["score"]
    return data


# ---------- auth ----------

@public_router.post("/auth/login", name="api_login")
async def login(request: Request):
    data = await _json_body(request)
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return _err("invalid email or password", 401)
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO api_tokens (token_hash, user_id) VALUES (?, ?)", (_hash(token), user["id"]))
    db.commit()
    return jsonify({"token": token, "user": _user_json(user)}, 201)


@router.post("/auth/logout", name="api_logout")
def logout(request: Request):
    db = get_db()
    db.execute("DELETE FROM api_tokens WHERE token_hash = ?", (_hash(_bearer_token(request)),))
    db.commit()
    return jsonify({"ok": True})


@router.get("/me")
def me(request: Request):
    return jsonify(_user_json(request.state.api_user))


@router.get("/me/analysis")
def my_analysis(request: Request):
    return jsonify(ml.analyze_user(get_db(), request.state.api_user["id"]))


# ---------- practice questions and attempts ----------

@router.get("/questions")
def list_questions(request: Request):
    category = request.query_params.get("category", "Mixed")
    try:
        count = max(1, min(20, int(request.query_params.get("count", 10))))
    except ValueError:
        return _err("count must be an integer")
    db = get_db()
    if category == "Mixed":
        rows = db.execute("SELECT * FROM questions ORDER BY RANDOM() LIMIT ?", (count,)).fetchall()
    else:
        if category not in CATEGORIES:
            return _err(f"category must be one of: Mixed, {', '.join(CATEGORIES)}")
        rows = db.execute(
            "SELECT * FROM questions WHERE category = ? ORDER BY RANDOM() LIMIT ?",
            (category, count)).fetchall()
    return jsonify({"category": category, "questions": [_question_json(r) for r in rows]})


@router.post("/attempts")
def create_attempt(request: Request):
    payload = _body(request)
    category = str(payload.get("category", "Mixed"))
    parsed, err = _parse_answers(payload)
    if err:
        return _err(err)
    t = payload.get("time_taken_seconds", 0)
    time_taken = t if isinstance(t, int) and not isinstance(t, bool) and t >= 0 else 0
    result, err = _record_attempt(get_db(), request.state.api_user["id"], category, parsed,
                                  time_taken=time_taken)
    if err:
        return _err(err)
    return jsonify(result, 201)


@router.get("/attempts")
def list_attempts(request: Request):
    rows = get_db().execute(
        "SELECT id, category, score, total, time_taken, created_at FROM attempts "
        "WHERE user_id = ? ORDER BY id DESC LIMIT 50", (request.state.api_user["id"],)).fetchall()
    return jsonify({"attempts": [dict(r) for r in rows]})


# ---------- daily test ----------

@router.get("/daily")
def daily_status(request: Request):
    db = get_db()
    uid = request.state.api_user["id"]
    day = daily.today()
    done = daily.completed(db, uid, day)
    data = {
        "date": day.isoformat(),
        "completed": done is not None,
        "attempt_id": done["attempt_id"] if done else None,
        "streak": daily.streak(db, uid, day),
        "count": daily.DAILY_COUNT,
    }
    if done is None:
        data["questions"] = _questions_by_ids(db, daily.pick_questions(db, uid, day))
    return jsonify(data)


@router.post("/daily/submit")
def daily_submit(request: Request):
    db = get_db()
    uid = request.state.api_user["id"]
    day = daily.today()
    if daily.completed(db, uid, day):
        return _err("today's daily test is already completed", 409)
    parsed, err = _parse_answers(_body(request))
    if err:
        return _err(err)
    allowed = set(daily.pick_questions(db, uid, day))
    if not {qid for qid, _ in parsed} <= allowed:
        return _err("answers must belong to today's daily set")
    result, err = _record_attempt(db, uid, "Daily practice", parsed, daily_date=day.isoformat())
    if err:
        return _err(err)
    return jsonify(result, 201)


# ---------- mock interviews ----------

@router.get("/interviews")
def list_interviews(request: Request):
    rows = interview.sessions_summary(get_db(), request.state.api_user["id"])
    return jsonify({"interviews": [dict(r) for r in rows]})


@router.post("/interviews")
def create_interview(request: Request):
    db = get_db()
    payload = _body(request)
    itype = str(payload.get("type", "Mixed"))
    if itype != "Mixed" and itype not in interview.TYPES:
        return _err(f"type must be Mixed or one of: {', '.join(interview.TYPES)}")
    try:
        count = max(3, min(5, int(payload.get("count", 3))))
    except (TypeError, ValueError):
        return _err("count must be an integer between 3 and 5")
    qids = interview.pick_questions(db, itype, count)
    if not qids:
        return _err("no interview questions available for that type", 404)
    cur = db.execute("INSERT INTO interview_sessions (user_id, interview_type) VALUES (?, ?)",
                     (request.state.api_user["id"], itype))
    sid = cur.lastrowid
    db.executemany("INSERT INTO interview_items (session_id, position, question_id) VALUES (?, ?, ?)",
                   [(sid, i + 1, q) for i, q in enumerate(qids)])
    db.commit()
    return jsonify({"session_id": sid, "type": itype, "items": _session_items(db, sid)}, 201)


def _session_items(db, sid):
    rows = db.execute(
        """SELECT i.id, i.position, i.answer, i.score, q.text AS question, q.interview_type
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.session_id = ? ORDER BY i.position""", (sid,)).fetchall()
    return [_item_json(r) for r in rows]


@router.get("/interviews/{session_id}")
def get_interview(session_id: int, request: Request):
    db = get_db()
    s = _own_session(db, session_id, request.state.api_user)
    if s is None:
        return _err("interview not found", 404)
    items = _session_items(db, session_id)
    return jsonify({
        "session_id": s["id"],
        "type": s["interview_type"],
        "created_at": s["created_at"],
        "completed": all(i["answered"] for i in items),
        "items": items,
    })


@router.post("/interviews/{session_id}/items/{item_id}/answer")
def answer_interview_item(session_id: int, item_id: int, request: Request):
    db = get_db()
    s = _own_session(db, session_id, request.state.api_user)
    if s is None:
        return _err("interview not found", 404)
    item = db.execute(
        """SELECT i.id, i.answer, q.interview_type, q.keywords
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.id = ? AND i.session_id = ?""", (item_id, session_id)).fetchone()
    if item is None:
        return _err("question not found in this interview", 404)
    if item["answer"] is not None:
        return _err("this question has already been answered", 409)
    raw = _body(request).get("answer", "")
    text = raw.strip()[:4000] if isinstance(raw, str) else ""
    res = interview.score_answer(text, item["interview_type"], item["keywords"])
    db.execute(
        """UPDATE interview_items SET answer = ?, score = ?, word_count = ?, filler_count = ?,
           answered_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (text, res["score"], res["words"], res["filler_count"], item_id))
    db.commit()
    return jsonify({
        "item_id": item_id,
        "score": res["score"],
        "label": res["label"],
        "words": res["words"],
        "hits": res["hits"],
        "missed": res["missed"],
        "filler_count": res["filler_count"],
        "star": res["star"],
        "feedback": res["feedback"],
    })


@router.get("/interviews/{session_id}/report", name="api_interview_report")
def interview_report(session_id: int, request: Request):
    db = get_db()
    s = _own_session(db, session_id, request.state.api_user)
    if s is None:
        return _err("interview not found", 404)
    rows = db.execute(
        """SELECT i.*, q.text AS question, q.keywords, q.interview_type
           FROM interview_items i JOIN interview_questions q ON q.id = i.question_id
           WHERE i.session_id = ? ORDER BY i.position""", (session_id,)).fetchall()
    if not rows or any(r["answer"] is None for r in rows):
        return _err("interview is not finished yet", 409)
    items = []
    for r in rows:
        res = interview.score_answer(r["answer"], r["interview_type"], r["keywords"])
        items.append({
            "position": r["position"],
            "question": r["question"],
            "answer": r["answer"],
            "score": r["score"],
            "label": res["label"],
            "hits": res["hits"],
            "missed": res["missed"],
            "feedback": res["feedback"],
        })
    avg = round(sum(r["score"] for r in rows) / len(rows), 1)
    return jsonify({
        "session_id": session_id,
        "type": s["interview_type"],
        "average": avg,
        "label": interview.label(avg),
        "items": items,
    })


# ---------- career ----------

@router.get("/roles")
def roles(request: Request):
    db = get_db()
    out = []
    for r in db.execute("SELECT * FROM job_roles ORDER BY title"):
        topics = career.role_topics(db, r["id"])
        out.append({
            "id": r["id"],
            "title": r["title"],
            "description": r["description"],
            "aptitude_categories": [c for c in r["aptitude_categories"].split(",") if c],
            "topics": [{"topic": t["topic"], "guidance": t["guidance"]} for t in topics],
        })
    return jsonify({"roles": out})


@router.get("/companies")
def companies(request: Request):
    rows = get_db().execute("SELECT id, name, sector FROM companies ORDER BY name").fetchall()
    return jsonify({"companies": [dict(r) for r in rows]})


@router.get("/companies/{company_id}")
def company_detail(company_id: int, request: Request):
    db = get_db()
    c = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if c is None:
        return _err("company not found", 404)
    rounds = []
    for group in career.company_questions(db, company_id):
        rounds.append({
            "round": group["round"],
            "questions": [{
                "question": q["question"],
                "year": q["year"],
                "source_url": q["source_url"],
                "source_note": q["source_note"],
            } for q in group["items"]],
        })
    alumni = [{
        "name": a["name"],
        "role_title": a["role_title"],
        "batch_year": a["batch_year"],
        "phone": a["phone"],
        "public_email": a["public_email"],
    } for a in career.public_alumni(db, company_id)]
    return jsonify({
        "id": c["id"],
        "name": c["name"],
        "sector": c["sector"],
        "hiring_process": c["hiring_process"],
        "question_rounds": rounds,
        "alumni": alumni,
    })


@router.get("/career/target")
def get_target(request: Request):
    db = get_db()
    uid = request.state.api_user["id"]
    t = career.get_target(db, uid)
    if t is None:
        return jsonify({"target": None})
    return jsonify({"target": {
        "role_id": t["role_id"],
        "role_title": t["role_title"],
        "company_id": t["company_id"],
        "company": career.target_company_name(t),
        "position_title": t["position_title"],
    }, "readiness": career.readiness(db, uid, t)})


@router.put("/career/target")
def put_target(request: Request):
    payload = _body(request)
    role_id = payload.get("role_id")
    if not isinstance(role_id, int) or isinstance(role_id, bool):
        return _err("role_id is required and must be an integer")
    company_id = payload.get("company_id")
    if company_id is not None and (not isinstance(company_id, int) or isinstance(company_id, bool)):
        return _err("company_id must be an integer or null")
    ok, err = career.save_target(
        get_db(), request.state.api_user["id"], role_id,
        company_id=company_id,
        company_name=str(payload.get("company_name", "") or ""),
        position_title=str(payload.get("position_title", "") or ""))
    if not ok:
        return _err(err)
    return get_target(request)


@router.post("/alumni")
def join_alumni(request: Request):
    payload = _body(request)
    company_id = payload.get("company_id")
    if company_id is not None and (not isinstance(company_id, int) or isinstance(company_id, bool)):
        return _err("company_id must be an integer or null")
    ok, err = career.save_alumni(
        get_db(), request.state.api_user["id"],
        company_id=company_id,
        company_name=str(payload.get("company_name", "") or ""),
        role_title=str(payload.get("role_title", "") or ""),
        batch_year=str(payload.get("batch_year", "") or ""),
        phone=str(payload.get("phone", "") or ""),
        public_email=str(payload.get("public_email", "") or ""),
        consent=payload.get("consent") is True)
    if not ok:
        return _err(err)
    return jsonify({"ok": True, "verified": False,
                    "note": "Your profile is listed once the placement cell verifies it."}, 201)


@router.delete("/alumni")
def leave_alumni(request: Request):
    career.remove_alumni(get_db(), request.state.api_user["id"])
    return jsonify({"ok": True})

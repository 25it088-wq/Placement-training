"""Daily test: one fresh set of questions per student per day, tuned to weak areas.

- Dates use Indian Standard Time, so "today" matches the students' day.
- The set is deterministic per student and date (a refresh does not reshuffle it).
- Categories are ordered weakest first using the ML analysis in ml.py.
"""
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import ml

DAILY_COUNT = 5
TZ = ZoneInfo("Asia/Kolkata")
RANK = {"weak": 0, "untested": 1, "developing": 2, "strong": 3}


def today():
    return datetime.now(TZ).date()


def focus_order(analysis):
    """Categories sorted from most to least in need of practice."""
    return sorted(analysis["categories"], key=lambda c: (RANK[c["status"]], c["score"]))


def pick_questions(conn, user_id, day, count=DAILY_COUNT):
    analysis = ml.analyze_user(conn, user_id)
    cats = [c["category"] for c in focus_order(analysis)]
    if not cats:
        return []

    pools = {}
    for r in conn.execute("SELECT id, category FROM questions"):
        pools.setdefault(r["category"], []).append(r["id"])

    rng = random.Random(f"{user_id}:{day.isoformat()}")
    # Round-robin over categories in priority order: every category gets at
    # least one question and the weakest one gets the extra slot.
    slots = [cats[i % len(cats)] for i in range(count)]
    chosen = []
    for cat in slots:
        pool = [q for q in pools.get(cat, []) if q not in chosen]
        if pool:
            chosen.append(rng.choice(pool))
    rng.shuffle(chosen)
    return chosen


def completed(conn, user_id, day):
    return conn.execute(
        "SELECT attempt_id FROM daily_tests WHERE user_id = ? AND test_date = ?",
        (user_id, day.isoformat())).fetchone()


def streak(conn, user_id, day):
    """Consecutive days with a completed test. Today's gap does not break it until tomorrow."""
    done = {date.fromisoformat(r["test_date"]) for r in conn.execute(
        "SELECT test_date FROM daily_tests WHERE user_id = ?", (user_id,))}
    cur = day if day in done else day - timedelta(days=1)
    n = 0
    while cur in done:
        n += 1
        cur -= timedelta(days=1)
    return n


def history(conn, user_id, day, days=14):
    done = {r["test_date"] for r in conn.execute(
        "SELECT test_date FROM daily_tests WHERE user_id = ?", (user_id,))}
    out = []
    for back in range(days - 1, -1, -1):
        d = day - timedelta(days=back)
        out.append({
            "iso": d.isoformat(),
            "label": d.strftime("%a"),
            "num": d.day,
            "done": d.isoformat() in done,
            "today": back == 0,
        })
    return out

"""Tests for the daily test and mock interview features.

Run: python3 test_features.py
"""
import os
import re
import sqlite3
import tempfile
from datetime import timedelta

os.environ["TRAINER_DB"] = os.path.join(tempfile.mkdtemp(), "features.db")

import app as appmod  # noqa: E402
import daily  # noqa: E402
import interview  # noqa: E402
from db import DB_PATH, get_db  # noqa: E402

app = appmod.app
app.config["TESTING"] = True
KW_HR = "education,skill,project,experience,goal,interest"

# ---------- scoring unit tests ----------

empty = interview.score_answer("", "HR", KW_HR)
assert empty["score"] == 0 and empty["words"] == 0

one_liner = interview.score_answer("I am good.", "HR", KW_HR)
rich = interview.score_answer(
    "I completed my B.Tech in computer science. My key skill is Python and I built a web "
    "project for the college library. My goal is to work on backend systems and grow my "
    "experience in cloud platforms. I enjoy solving problems and learning new tools.",
    "HR", KW_HR)
assert rich["score"] > one_liner["score"] + 30, (rich["score"], one_liner["score"])
assert "interest" in rich["missed"] and "skill" in rich["hits"]

star = interview.score_answer(
    "When I was in a team project, my role was to lead the backend. I decided to split the "
    "work into weekly sprints. As a result we delivered on time and the score improved by 20%.",
    "Behavioural", "team,challenge,result")
assert all(star["star"].values()), star["star"]

fillers = interview.score_answer("Um, basically, you know, I think I am good at Python, um.",
                                 "HR", "python")
assert fillers["filler_count"] >= 3
assert any("filler" in t for t in fillers["feedback"])

print("scoring: ok")

# ---------- daily test ----------

c = app.test_client()
r = c.post("/register", data={"name": "Tara", "email": "tara@x.dev", "password": "secret1"})
assert r.status_code == 302

# Daily set is deterministic for a given user and date
with app.app_context():
    db = get_db()
    uid = db.execute("SELECT id FROM users WHERE email='tara@x.dev'").fetchone()["id"]
    day = daily.today()
    a1 = daily.pick_questions(db, uid, day)
    a2 = daily.pick_questions(db, uid, day)
    assert a1 == a2 and len(a1) == daily.DAILY_COUNT, (a1, a2)
    assert len(set(a1)) == len(a1)

r = c.post("/daily/start")
assert r.status_code == 302 and r.headers["Location"].endswith("/quiz"), r.headers
page = c.get("/quiz").get_data(as_text=True)
ids = list(dict.fromkeys(re.findall(r'name="q(\d+)"', page)))
assert len(ids) == daily.DAILY_COUNT, ids
assert "Daily practice test" in page

c.post("/quiz/submit", data={f"q{i}": "0" for i in ids})

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
# The test DB is separate from the app DB: check it through the app instead
conn.close()

with app.app_context():
    db = get_db()
    rows = db.execute("SELECT * FROM daily_tests WHERE user_id = ?", (uid,)).fetchall()
    assert len(rows) == 1 and rows[0]["attempt_id"], "daily test not recorded"
    assert daily.streak(db, uid, day) == 1

# A second start on the same day is refused
r = c.post("/daily/start")
assert r.status_code == 302 and r.headers["Location"].endswith("/daily"), r.headers["Location"]

# Streak across days: give the user two earlier completed days
with app.app_context():
    db = get_db()
    for back in (2, 3):
        db.execute("INSERT INTO daily_tests (user_id, test_date) VALUES (?, ?)",
                   (uid, (day - timedelta(days=back)).isoformat()))
    db.commit()
    assert daily.streak(db, uid, day) == 1  # days 2 and 3 are not consecutive with day 0
    db.execute("INSERT INTO daily_tests (user_id, test_date) VALUES (?, ?)",
               (uid, (day - timedelta(days=1)).isoformat()))
    db.commit()
    assert daily.streak(db, uid, day) == 4, daily.streak(db, uid, day)

assert c.get("/daily").status_code == 200
print("daily test: ok")

# ---------- mock interview ----------

r = c.post("/interview/start", data={"type": "Mixed", "count": "3"})
assert r.status_code == 302, r.status_code
sid = int(r.headers["Location"].rstrip("/").split("/")[-1])

# Report is not available until every question is answered
rep = c.get(f"/interview/{sid}/report")
assert rep.status_code == 302 and "report" not in rep.headers["Location"]

answer_text = ("In my final year project I was responsible for the backend. I built the API, "
               "helped the team plan the work, and learned a lot. The result was a working demo "
               "delivered on time with clear results for the team.")
for _ in range(3):
    page = c.get(f"/interview/{sid}").get_data(as_text=True)
    assert "Interviewer" in page
    item_id = re.search(r'name="item_id" value="(\d+)"', page).group(1)
    c.post(f"/interview/{sid}/answer", data={"item_id": item_id, "answer": answer_text})

rep = c.get(f"/interview/{sid}/report")
assert rep.status_code == 200
body = rep.get_data(as_text=True)
assert "Interview report" in body and "Covered" in body

# Another student cannot open this session
other = app.test_client()
other.post("/register", data={"name": "Ravi", "email": "ravi@x.dev", "password": "secret1"})
assert other.get(f"/interview/{sid}").status_code == 404
assert other.get(f"/interview/{sid}/report").status_code == 404

# Pages render
assert c.get("/interview").status_code == 200
assert c.get("/dashboard").status_code == 200
print("interview: ok")

print("\nall feature checks passed")

"""Simulated students to exercise the app and the ML analysis end to end."""
import os, random, re, sqlite3, tempfile

os.environ["TRAINER_DB"] = os.path.join(tempfile.mkdtemp(), "sim.db")
import app as appmod
from fastapi.testclient import TestClient
import ml
from db import DB_PATH, init_db

app = appmod.app
random.seed(7)

# Each simulated student has a different skill profile per category.
PROFILES = {
    "Ana":   {"Quantitative Aptitude": .95, "Logical Reasoning": .90, "Verbal Ability": .35, "Data Interpretation": .85},
    "Ben":   {"Quantitative Aptitude": .30, "Logical Reasoning": .45, "Verbal Ability": .92, "Data Interpretation": .40},
    "Chloe": {"Quantitative Aptitude": .60, "Logical Reasoning": .60, "Verbal Ability": .60, "Data Interpretation": .60},
    "Dev":   {"Quantitative Aptitude": .88, "Logical Reasoning": .35, "Verbal Ability": .50, "Data Interpretation": .92},
    "Esha":  {"Quantitative Aptitude": .25, "Logical Reasoning": .30, "Verbal Ability": .40, "Data Interpretation": .20},
}

conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
keys = {r["id"]: (r["category"], r["answer"]) for r in conn.execute("SELECT id, category, answer FROM questions")}
conn.close()

for name, prof in PROFILES.items():
    c = TestClient(app, follow_redirects=False)
    email = name.lower() + "@test.dev"
    r = c.post("/register", data={"name": name, "email": email, "password": "secret1"})
    assert r.status_code == 302, r.status_code
    for _ in range(3):  # three tests each
        r = c.post("/quiz/start", data={"category": "Mixed", "count": "15"})
        assert r.status_code == 302
        page = c.get("/quiz").text
        qids = [int(x) for x in re.findall(r'name="q(\d+)"', page)]
        assert qids, "quiz page had no questions"
        form = {}
        for qid in qids:
            cat, ans = keys[qid]
            form[f"q{qid}"] = str(ans if random.random() < prof[cat] else (ans + 1) % 4)
        r = c.post("/quiz/submit", data=form)
        assert r.status_code == 302, r.status_code
    # view pages
    assert c.get("/dashboard").status_code == 200
    assert c.get("/analysis").status_code == 200
    print(name, "done")

admin = TestClient(app, follow_redirects=False)
assert admin.post("/login", data={"email": "admin@trainer.local", "password": "admin123"}).status_code == 302
assert admin.get("/admin").status_code == 200
assert admin.get("/admin/questions/new").status_code == 200

# ML output for each student
db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
for name in PROFILES:
    uid = db.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()["id"]
    a = ml.analyze_user(db, uid)
    print(f"\n== {name}: answered={a['answered']} raw={a['raw_accuracy']}% trend={a['trend']} next={a['predicted_next']}")
    print("   strengths:", [s['category'] for s in a['strengths']])
    print("   weaknesses:", [w['category'] for w in a['weaknesses']])
    print("   profile:", a['cluster'])
    print("   notes:", a['notes'])
print("\nall checks passed")

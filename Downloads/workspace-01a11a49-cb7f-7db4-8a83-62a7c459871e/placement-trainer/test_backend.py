"""Tests for the career section, the alumni directory and the JSON API.

Run: python3 test_backend.py
"""
import os
import tempfile

os.environ["TRAINER_DB"] = os.path.join(tempfile.mkdtemp(), "backend.db")

import app as appmod  # noqa: E402
import career  # noqa: E402
from db import get_db  # noqa: E402

app = appmod.app
app.config["TESTING"] = True
ADMIN = {"email": "admin@trainer.local", "password": "admin123"}


def one(sql, args=()):
    with app.app_context():
        return get_db().execute(sql, args).fetchone()


def role_id(title):
    return one("SELECT id FROM job_roles WHERE title = ?", (title,))["id"]


def company_id(name):
    return one("SELECT id FROM companies WHERE name = ?", (name,))["id"]


# ---------- seed data ----------

with app.app_context():
    db = get_db()
    assert db.execute("SELECT COUNT(*) FROM job_roles").fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 5
    tcs = company_id("TCS")
    rounds = [g["round"] for g in career.company_questions(db, tcs)]
    assert rounds == ["Technical", "HR"], rounds
    total_q = sum(len(g["items"]) for g in career.company_questions(db, tcs))
    assert total_q == 15, total_q
    for g in career.company_questions(db, tcs):
        for q in g["items"]:
            assert q["source_url"].startswith("http"), q["question"]
            assert q["year"], q["question"]
print("seed data: ok")

# ---------- career logic (unit) ----------

with app.app_context():
    db = get_db()
    db.execute("INSERT INTO users (name, email, password_hash, role) VALUES ('Ravi', 'ravi@x.dev', 'x', 'student')")
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE email='ravi@x.dev'").fetchone()["id"]

    ok, err = career.save_target(db, uid, 999, company_id=tcs, position_title="X")
    assert not ok and "role" in err
    ok, err = career.save_target(db, uid, role_id("Software Developer"), company_id=-5, position_title="X")
    assert not ok and "company" in err
    ok, err = career.save_target(db, uid, role_id("Software Developer"), company_name="  ", position_title="X")
    assert not ok
    ok, _ = career.save_target(db, uid, role_id("Software Developer"), company_id=tcs,
                               position_title="Associate Software Engineer")
    assert ok
    t = career.get_target(db, uid)
    assert t["company_id"] == tcs and career.target_company_name(t) == "TCS"

    # No interview history: readiness is the aptitude score alone.
    r = career.readiness(db, uid, t)
    assert r["interview"] is None
    assert r["readiness"] == r["aptitude"], r
    assert r["categories"] == ["Quantitative Aptitude", "Logical Reasoning"]

    # Free-text company is stored without an id.
    ok, _ = career.save_target(db, uid, role_id("Data Analyst"), company_name="Acme Labs", position_title="Analyst")
    t = career.get_target(db, uid)
    assert t["company_id"] is None and career.target_company_name(t) == "Acme Labs"
    career.save_target(db, uid, role_id("Software Developer"), company_id=tcs, position_title="ASE")

    # Alumni: consent is required.
    ok, err = career.save_alumni(db, uid, tcs, "", "Associate", consent=False)
    assert not ok and "agree" in err
    ok, _ = career.save_alumni(db, uid, tcs, "", "Associate", batch_year="2025",
                               phone="9999999999", public_email="ravi@mail.dev", consent=True)
    assert ok
    assert career.public_alumni(db, tcs) == []  # not verified yet

    db.execute("UPDATE alumni_profiles SET verified = 1 WHERE user_id = ?", (uid,))
    db.commit()
    shown = career.public_alumni(db, tcs)
    assert len(shown) == 1 and shown[0]["name"] == "Ravi"

    # Editing sends the profile back for verification.
    career.save_alumni(db, uid, tcs, "", "Senior Associate", consent=True)
    assert db.execute("SELECT verified FROM alumni_profiles WHERE user_id = ?", (uid,)).fetchone()["verified"] == 0
    assert career.public_alumni(db, tcs) == []

    career.remove_alumni(db, uid)
    assert db.execute("SELECT COUNT(*) FROM alumni_profiles WHERE user_id = ?", (uid,)).fetchone()[0] == 0
print("career logic: ok")

# ---------- web pages ----------

c = app.test_client()
r = c.post("/register", data={"name": "Meena", "email": "meena@x.dev", "password": "secret1"})
assert r.status_code == 302
r = c.get("/career")
assert r.status_code == 200 and b"Set your target" in r.data

r = c.post("/career/target", data={"role_id": "", "position_title": "X"}, follow_redirects=True)
assert b"Choose a job role" in r.data
r = c.post("/career/target", data={"role_id": str(role_id("Software Developer")), "position_title": ""},
           follow_redirects=True)
assert b"Enter the position" in r.data
r = c.post("/career/target", data={"role_id": str(role_id("Software Developer")),
                                   "company_id": str(company_id("TCS")),
                                   "position_title": "Associate Software Engineer"}, follow_redirects=True)
assert r.status_code == 200 and b"Career target saved" in r.data
assert b"Previous interview questions" in r.data
assert b"Associate Software Engineer" in r.data
assert b"Alumni placed at TCS" in r.data
assert b"reverse a string" in r.data.lower()

# Alumni form: consent required by the server too.
r = c.post("/career/alumni", data={"company_id": str(company_id("TCS")), "role_title": "Associate"},
           follow_redirects=True)
assert b"You must agree" in r.data
r = c.post("/career/alumni", data={"company_id": str(company_id("TCS")), "role_title": "Associate",
                                   "consent": "on", "public_email": "meena.a@mail.dev"},
           follow_redirects=True)
assert b"verifies it" in r.data
assert one("SELECT verified FROM alumni_profiles a JOIN users u ON u.id=a.user_id WHERE u.email='meena@x.dev'")["verified"] == 0

# Admin verifies the profile through the web admin page.
adm = app.test_client()
assert adm.post("/login", data=ADMIN).status_code == 302
r = adm.get("/admin/career")
assert r.status_code == 200 and b"meena.a@mail.dev" in r.data  # public email shown to the verifier
aid = one("SELECT a.id FROM alumni_profiles a JOIN users u ON u.id=a.user_id WHERE u.email='meena@x.dev'")["id"]
r = adm.post(f"/admin/alumni/{aid}/verify", follow_redirects=True)
assert b"verified and listed" in r.data
r = c.get("/career")
assert b"meena.a@mail.dev" in r.data

# Admin adds a company question; a bad source link is dropped, not stored.
r = adm.post("/admin/company-questions/new", data={
    "company_id": str(company_id("TCS")), "round_type": "HR", "question": "Why do you want to join us?",
    "year": "2025", "source_url": "javascript:alert(1)", "source_note": "test"}, follow_redirects=True)
assert b"Question added" in r.data
assert one("SELECT source_url FROM company_questions WHERE question = 'Why do you want to join us?'")["source_url"] == ""

r = adm.post("/admin/company-questions/new", data={
    "company_id": "9999", "round_type": "HR", "question": "Q"}, follow_redirects=True)
assert b"Choose a valid company" in r.data

r = adm.post("/admin/companies/new", data={"name": "TCS", "sector": "IT"}, follow_redirects=True)
assert b"already exists" in r.data
r = adm.post("/admin/companies/new", data={"name": "Zoho Test", "sector": "Software"}, follow_redirects=True)
assert b"Company added" in r.data

# Students cannot reach admin career pages.
assert c.get("/admin/career").status_code in (302, 403)

# Leaving the directory from the web.
r = c.post("/career/alumni", data={"action": "remove"}, follow_redirects=True)
assert b"removed from the alumni directory" in r.data
assert one("SELECT COUNT(*) AS n FROM alumni_profiles a JOIN users u ON u.id=a.user_id WHERE u.email='meena@x.dev'")["n"] == 0
print("web pages: ok")

# ---------- JSON API ----------

api = app.test_client()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


r = api.get("/api/v1/me")
assert r.status_code == 401 and r.get_json()["error"]
r = api.post("/api/v1/auth/login", json={"email": "meena@x.dev", "password": "wrong"})
assert r.status_code == 401 and "error" in r.get_json()

r = api.post("/api/v1/auth/login", json={"email": "meena@x.dev", "password": "secret1"})
assert r.status_code == 201
token = r.get_json()["token"]
assert "password_hash" not in r.get_json()["user"]

r = api.get("/api/v1/me", headers=auth(token))
assert r.status_code == 200

r = api.get("/api/v1/roles", headers=auth(token))
roles = r.get_json()["roles"]
assert len(roles) == 4 and all(r_["topics"] for r_ in roles)

r = api.get("/api/v1/companies", headers=auth(token))
names = [c_["name"] for c_ in r.get_json()["companies"]]
assert "TCS" in names

tcs = company_id("TCS")
r = api.get(f"/api/v1/companies/{tcs}", headers=auth(token))
detail = r.get_json()
assert r.status_code == 200 and detail["name"] == "TCS"
assert len(detail["question_rounds"]) >= 2
assert detail["alumni"] == []  # nothing verified in this run yet
assert api.get("/api/v1/companies/9999", headers=auth(token)).status_code == 404

r = api.get("/api/v1/career/target", headers=auth(token))
assert r.get_json()["target"]["company"] == "TCS"  # set earlier through the web form

r = api.put("/api/v1/career/target", headers=auth(token), json={"role_id": "x"})
assert r.status_code == 400 and "error" in r.get_json()
r = api.put("/api/v1/career/target", headers=auth(token),
            json={"role_id": role_id("Data Analyst"), "company_id": tcs, "position_title": "Analyst"})
assert r.status_code == 200
body = r.get_json()
assert body["target"]["company"] == "TCS" and body["target"]["position_title"] == "Analyst"
assert "readiness" in body and body["readiness"]["readiness"] >= 0

r = api.post("/api/v1/alumni", headers=auth(token), json={"company_id": tcs, "role_title": "Analyst"})
assert r.status_code == 400 and "agree" in r.get_json()["error"]
r = api.post("/api/v1/alumni", headers=auth(token),
             json={"company_id": tcs, "role_title": "Analyst", "consent": True, "batch_year": "2026"})
assert r.status_code == 201 and r.get_json()["verified"] is False

# Admin verifies over the web, then the API shows the alumni.
aid = one("SELECT a.id FROM alumni_profiles a JOIN users u ON u.id=a.user_id WHERE u.email='meena@x.dev'")["id"]
adm.post(f"/admin/alumni/{aid}/verify")
detail = api.get(f"/api/v1/companies/{tcs}", headers=auth(token)).get_json()
assert len(detail["alumni"]) == 1 and detail["alumni"][0]["role_title"] == "Analyst"

r = api.delete("/api/v1/alumni", headers=auth(token))
assert r.get_json()["ok"] is True

r = api.get("/api/v1/attempts", headers=auth(token))
assert r.status_code == 200 and "attempts" in r.get_json()

r = api.post("/api/v1/auth/logout", headers=auth(token))
assert r.get_json()["ok"] is True
assert api.get("/api/v1/me", headers=auth(token)).status_code == 401
print("api: ok")

print("\nall backend checks passed")

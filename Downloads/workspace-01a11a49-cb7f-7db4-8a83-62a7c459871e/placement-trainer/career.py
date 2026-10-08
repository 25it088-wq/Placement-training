"""Career planning: target role and company, readiness score, company prep and the alumni directory.

Privacy rule: alumni appear in the directory only after they opt in
(consent_share = 1) and an admin verifies them. Only logged-in students
can see the directory.
"""
import interview
import ml

ROUND_ORDER = ["Aptitude", "Coding", "Technical", "HR"]
APTITUDE_WEIGHT = 0.7
INTERVIEW_WEIGHT = 0.3


def readiness_label(score):
    if score >= 75:
        return "Ready to apply"
    if score >= 55:
        return "Getting there"
    return "Needs focused practice"


def get_target(conn, user_id):
    return conn.execute(
        """SELECT ut.*, r.title AS role_title, r.aptitude_categories,
                  c.name AS company_db_name
           FROM user_targets ut
           JOIN job_roles r ON r.id = ut.role_id
           LEFT JOIN companies c ON c.id = ut.company_id
           WHERE ut.user_id = ?""", (user_id,)).fetchone()


def target_company_name(target):
    return target["company_db_name"] or target["company_name"]


def readiness(conn, user_id, target):
    """Blend aptitude scores for the role with interview practice (if any)."""
    analysis = ml.analyze_user(conn, user_id)
    scores = {c["category"]: c["score"] for c in analysis["categories"]}
    cats = [c.strip() for c in target["aptitude_categories"].split(",") if c.strip()]
    aptitude = round(sum(scores.get(c, 50.0) for c in cats) / len(cats), 1) if cats else 50.0

    sessions = interview.sessions_summary(conn, user_id)
    avgs = [s["avg_score"] for s in sessions if s["avg_score"] is not None]
    iv = round(sum(avgs) / len(avgs), 1) if avgs else None

    if iv is None:
        total = aptitude
    else:
        total = round(APTITUDE_WEIGHT * aptitude + INTERVIEW_WEIGHT * iv, 1)
    return {
        "readiness": total,
        "label": readiness_label(total),
        "aptitude": aptitude,
        "interview": iv,
        "categories": cats,
    }


def role_topics(conn, role_id):
    return conn.execute(
        "SELECT * FROM role_topics WHERE role_id = ? ORDER BY position", (role_id,)).fetchall()


def company_questions(conn, company_id):
    """Questions grouped by round, in ROUND_ORDER, newest year first."""
    rows = conn.execute(
        "SELECT * FROM company_questions WHERE company_id = ? ORDER BY year DESC, id",
        (company_id,)).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["round_type"], []).append(r)
    rounds = ROUND_ORDER + sorted(set(grouped) - set(ROUND_ORDER))
    return [{"round": rt, "items": grouped[rt]} for rt in rounds if rt in grouped]


def public_alumni(conn, company_id):
    """Alumni who opted in AND were verified by an admin."""
    return conn.execute(
        """SELECT a.role_title, a.batch_year, a.phone, a.public_email, u.name
           FROM alumni_profiles a JOIN users u ON u.id = a.user_id
           WHERE a.company_id = ? AND a.verified = 1 AND a.consent_share = 1
           ORDER BY u.name""", (company_id,)).fetchall()


def save_target(conn, user_id, role_id, company_id=None, company_name="", position_title=""):
    if conn.execute("SELECT id FROM job_roles WHERE id = ?", (role_id,)).fetchone() is None:
        return False, "Choose a valid role."
    company_name = (company_name or "").strip()[:100]
    if company_id is not None:
        c = conn.execute("SELECT id, name FROM companies WHERE id = ?", (company_id,)).fetchone()
        if c is None:
            return False, "Choose a valid company."
        company_name = c["name"]
    if not company_name:
        return False, "Choose a company or type one."
    position_title = (position_title or "").strip()[:100]
    conn.execute(
        """INSERT INTO user_targets (user_id, role_id, company_id, company_name, position_title)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               role_id = excluded.role_id, company_id = excluded.company_id,
               company_name = excluded.company_name, position_title = excluded.position_title,
               updated_at = CURRENT_TIMESTAMP""",
        (user_id, role_id, company_id, company_name, position_title))
    conn.commit()
    return True, None


def save_alumni(conn, user_id, company_id, company_name, role_title,
                batch_year="", phone="", public_email="", consent=False):
    """Create or update the user's alumni profile. Editing sends it back for verification."""
    if not consent:
        return False, "You must agree to share your details to join the directory."
    company_name = (company_name or "").strip()[:100]
    if company_id is not None:
        c = conn.execute("SELECT id, name FROM companies WHERE id = ?", (company_id,)).fetchone()
        if c is None:
            return False, "Choose a valid company."
        company_id, company_name = c["id"], c["name"]
    else:
        match = conn.execute(
            "SELECT id, name FROM companies WHERE LOWER(name) = LOWER(?)", (company_name,)).fetchone()
        company_id = match["id"] if match else None
        if match:
            company_name = match["name"]
    if not company_name:
        return False, "Enter the company you were placed in."
    role_title = (role_title or "").strip()[:100]
    if not role_title:
        return False, "Enter the role you were placed in."

    conn.execute(
        """INSERT INTO alumni_profiles
           (user_id, company_id, company_name, role_title, batch_year, phone, public_email, consent_share, verified)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
           ON CONFLICT(user_id) DO UPDATE SET
               company_id = excluded.company_id, company_name = excluded.company_name,
               role_title = excluded.role_title, batch_year = excluded.batch_year,
               phone = excluded.phone, public_email = excluded.public_email,
               consent_share = 1, verified = 0, created_at = CURRENT_TIMESTAMP""",
        (user_id, company_id, company_name, role_title,
         (batch_year or "").strip()[:10], (phone or "").strip()[:20], (public_email or "").strip()[:120]))
    conn.commit()
    return True, None


def remove_alumni(conn, user_id):
    conn.execute("DELETE FROM alumni_profiles WHERE user_id = ?", (user_id,))
    conn.commit()

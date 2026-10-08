"""SQLite database setup and connection helpers."""
import os
import sqlite3

from flask import g
from werkzeug.security import generate_password_hash

from career_data import COMPANIES, COMPANY_QUESTIONS, ROLES
from interview_data import INTERVIEW_QUESTIONS
from seed_data import QUESTIONS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TRAINER_DB", os.path.join(BASE_DIR, "trainer.db"))
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@trainer.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student',
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    difficulty  INTEGER NOT NULL DEFAULT 1,
    text        TEXT NOT NULL,
    option_a    TEXT NOT NULL,
    option_b    TEXT NOT NULL,
    option_c    TEXT NOT NULL,
    option_d    TEXT NOT NULL,
    answer      INTEGER NOT NULL,            -- index 0..3 of the correct option
    explanation TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    category   TEXT NOT NULL,                -- category chosen, 'Mixed' or 'Daily practice'
    score      INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    time_taken INTEGER DEFAULT 0,            -- seconds
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- One row per question answered. Category and difficulty are copied here so
-- the ML analysis can run without joining back to the question bank.
CREATE TABLE IF NOT EXISTS attempt_answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id  INTEGER NOT NULL REFERENCES attempts(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    category    TEXT NOT NULL,
    difficulty  INTEGER NOT NULL,
    selected    INTEGER,                     -- NULL if skipped
    is_correct  INTEGER NOT NULL
);

-- One completed daily test per student per calendar day (IST).
CREATE TABLE IF NOT EXISTS daily_tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    test_date  TEXT NOT NULL,                -- YYYY-MM-DD
    attempt_id INTEGER REFERENCES attempts(id),
    UNIQUE(user_id, test_date)
);

CREATE TABLE IF NOT EXISTS interview_questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_type  TEXT NOT NULL,           -- HR, Behavioural or Technical
    text            TEXT NOT NULL,
    keywords        TEXT NOT NULL            -- comma-separated expected concepts
);

CREATE TABLE IF NOT EXISTS interview_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    interview_type  TEXT NOT NULL,           -- chosen type or 'Mixed'
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- One row per question in an interview. answer stays NULL until submitted.
CREATE TABLE IF NOT EXISTS interview_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES interview_sessions(id),
    position     INTEGER NOT NULL,
    question_id  INTEGER NOT NULL REFERENCES interview_questions(id),
    answer       TEXT,
    score        REAL,
    word_count   INTEGER,
    filler_count INTEGER,
    answered_at  TEXT
);

-- Career section -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_roles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT UNIQUE NOT NULL,
    description         TEXT DEFAULT '',
    aptitude_categories TEXT NOT NULL        -- comma-separated quiz categories used for readiness
);

CREATE TABLE IF NOT EXISTS role_topics (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id  INTEGER NOT NULL REFERENCES job_roles(id),
    position INTEGER NOT NULL,
    topic    TEXT NOT NULL,
    guidance TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    sector          TEXT DEFAULT '',
    hiring_process  TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    round_type  TEXT NOT NULL,               -- Aptitude, Coding, Technical or HR
    question    TEXT NOT NULL,
    year        TEXT DEFAULT '',
    source_url  TEXT DEFAULT '',
    source_note TEXT DEFAULT '',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_targets (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id),
    role_id        INTEGER NOT NULL REFERENCES job_roles(id),
    company_id     INTEGER REFERENCES companies(id),
    company_name   TEXT DEFAULT '',
    position_title TEXT DEFAULT '',
    updated_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Opt-in alumni directory. A row exists only if the person agreed to share.
-- verified = 1 only after an admin has checked the record.
CREATE TABLE IF NOT EXISTS alumni_profiles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER UNIQUE NOT NULL REFERENCES users(id),
    company_id    INTEGER REFERENCES companies(id),
    company_name  TEXT NOT NULL,
    role_title    TEXT NOT NULL,
    batch_year    TEXT DEFAULT '',
    phone         TEXT DEFAULT '',
    public_email  TEXT DEFAULT '',
    consent_share INTEGER NOT NULL DEFAULT 0,
    verified      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- API bearer tokens, stored as SHA-256 hashes.
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_answers_user ON attempt_answers(user_id, category);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_daily_user ON daily_tests(user_id, test_date);
CREATE INDEX IF NOT EXISTS idx_items_session ON interview_items(session_id, position);
CREATE INDEX IF NOT EXISTS idx_alumni_company ON alumni_profiles(company_id, verified);
CREATE INDEX IF NOT EXISTS idx_company_q ON company_questions(company_id, round_type);
"""


def get_db():
    """Return a per-request database connection."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _seed_career(conn):
    if conn.execute("SELECT COUNT(*) FROM job_roles").fetchone()[0] == 0:
        for role in ROLES:
            cur = conn.execute(
                "INSERT INTO job_roles (title, description, aptitude_categories) VALUES (?, ?, ?)",
                (role["title"], role["description"], ",".join(role["aptitude"])))
            conn.executemany(
                "INSERT INTO role_topics (role_id, position, topic, guidance) VALUES (?, ?, ?, ?)",
                [(cur.lastrowid, i + 1, t, g) for i, (t, g) in enumerate(role["topics"])])

    if conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO companies (name, sector, hiring_process) VALUES (?, ?, ?)",
            [(c["name"], c["sector"], c["hiring_process"]) for c in COMPANIES])

    if conn.execute("SELECT COUNT(*) FROM company_questions").fetchone()[0] == 0:
        for name, items in COMPANY_QUESTIONS.items():
            row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
            if row:
                conn.executemany(
                    """INSERT INTO company_questions
                       (company_id, round_type, question, year, source_url, source_note)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [(row[0], rt, q, yr, url, note) for rt, q, yr, url, note in items])


def init_db():
    """Create tables, seed the question banks, and create a default admin if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    if conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0:
        conn.executemany(
            """INSERT INTO questions
               (category, difficulty, text, option_a, option_b, option_c, option_d, answer, explanation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(c, d, t, *opts, a, e) for c, d, t, opts, a, e in QUESTIONS],
        )

    if conn.execute("SELECT COUNT(*) FROM interview_questions").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO interview_questions (interview_type, text, keywords) VALUES (?, ?, ?)",
            [(t, q, ",".join(k)) for t, q, k in INTERVIEW_QUESTIONS],
        )
    else:
        # Keep keyword lists in sync with the bank for databases seeded by an older version.
        conn.executemany(
            "UPDATE interview_questions SET keywords = ? WHERE interview_type = ? AND text = ?",
            [(",".join(k), t, q) for t, q, k in INTERVIEW_QUESTIONS],
        )

    _seed_career(conn)

    if conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("Placement Cell", ADMIN_EMAIL, generate_password_hash(ADMIN_PASSWORD)),
        )

    conn.commit()
    conn.close()

# Placement Trainer

A FastAPI web app that helps college students prepare for campus placements.
Students take timed aptitude tests, a daily test, and mock interviews, then
review explanations. A machine-learning analysis shows where they are strong and
where they need work. The career section trains them for a specific job role,
position and target company. Admins (placement cell) manage the question banks,
company data and the alumni directory.

## Features
- **Student accounts**: register and log in.
- **Timed aptitude tests**: Quantitative Aptitude, Logical Reasoning, Verbal Ability, Data Interpretation. Mixed or single category, 5 to 20 questions, 60 seconds per question.
- **Daily test**: a fixed set of questions per user per day, weighted toward weaker categories. Tracks a streak.
- **Mock interviews**: HR, Behavioural and Technical questions. Answers are scored by keyword and concept coverage, with filler-word feedback and a STAR check for behavioural answers. Scoring is heuristic, not AI. A report summarises each session.
- **Career section**: pick a job role, company and position. See a readiness score, a training plan for the role, and previous-year interview questions for the company (grouped by round, each with its source and year). Shows verified alumni of that company.
- **Alumni directory (opt-in)**: alumni submit their own details and consent to share them. An admin verifies each profile. Only verified, consenting alumni appear on company pages. Editing a profile sends it back for verification.
- **Result review**: every answer with the correct option and an explanation.
- **ML performance analysis** (`ml.py`):
  - Bayesian-smoothed accuracy per category, so a few lucky answers do not look like mastery.
  - Peer z-scores: how a student compares with the other students in each category.
  - KMeans clustering of students into learning profiles (for example, "Strong in Verbal Ability, needs work in Data Interpretation").
  - Linear regression over the score history for the trend and a predicted next score.
  - Strength and weakness labels, plus recommendations.
- **Career readiness**: 0.7 × the average of the role's aptitude categories + 0.3 × the average interview score. With no interview practice, readiness is the aptitude score alone.
- **Admin dashboard**: cohort accuracy by category, a per-student table, a form to add questions, and a Career admin page (companies, previous-year questions, alumni verification).
- **JSON API** (`api.py`): REST endpoints under `/api/v1` with bearer-token login. Covers quizzes, daily test, interviews, analysis and career. See `docs/API.md`.

## Run it
```bash
pip install -r requirements.txt
python3 app.py            # http://localhost:5000
# or, with auto-reload while developing:
uvicorn app:app --reload --host 0.0.0.0 --port 5000
```
The database (`trainer.db`), the starter question banks, interview questions, job roles and TCS company data are created on first run.

Default admin login: `admin@trainer.local` / `admin123`. Change it before real use:
```bash
ADMIN_EMAIL=you@college.edu ADMIN_PASSWORD='a-strong-password' python3 app.py
```
This only applies when the database is created for the first time. Otherwise change the password in the database.
Set `SECRET_KEY` in production as well (it signs the login session cookie).

Set the database location with `TRAINER_DB=/path/to/file.db`.

## Career data and sources
- Company questions are seeded only for TCS, from candidate-reported and prep-site articles dated 2024 and 2025. Each entry records its source link and year. They are not verified against the company, and rounds change by year and profile.
- Infosys, Wipro, Accenture and Cognizant are listed with no questions yet. The placement cell can add them on the Career admin page.
- Alumni contact details are never seeded or scraped. The directory fills only when alumni join and an admin verifies them.

## API
```bash
TOKEN=$(curl -s -X POST localhost:5000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@college.edu","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s localhost:5000/api/v1/career/target -H "Authorization: Bearer $TOKEN"
```
Full reference: `docs/API.md`.

## Tests
```bash
python3 test_simulation.py   # five simulated students through the app, with ML output
python3 test_features.py     # daily test, mock interviews and scoring
python3 test_backend.py      # career section, alumni flow, web pages and JSON API
```

## Project layout
```
app.py              FastAPI routes (auth, quiz, results, analysis, daily, interview, career, admin)
api.py              JSON API (/api/v1), bearer-token auth (FastAPI router)
career.py           Career logic: targets, readiness, company questions, alumni
career_data.py      Seed data: job roles, companies, TCS previous-year questions
ml.py               Performance analysis: smoothing, peer z-scores, KMeans, trend
daily.py            Daily test selection, streaks and history
interview.py        Interview scoring and session summaries
interview_data.py   Interview question bank
db.py               SQLite schema, per-request connections, first-run setup and seeding
seed_data.py        Aptitude question bank
templates/          Jinja2 pages
static/             Styling (style.css, features.css)
docs/API.md         API reference
test_*.py           Tests
```

## Notes and limits
- The ML needs data. Results are labelled "low confidence" until a category has about 5 answers, and the peer comparison and clustering need at least 3 active students.
- Interview scoring is keyword-based. It is a practice aid, not a real assessment.
- Forms do not yet have CSRF protection. Add a CSRF token check (for example, a hidden field plus middleware) before deploying publicly.
- No API rate limiting yet.
- Not yet built: coding practice, resume builder, AI question generation (needs an API key), and admin editing of interview questions.

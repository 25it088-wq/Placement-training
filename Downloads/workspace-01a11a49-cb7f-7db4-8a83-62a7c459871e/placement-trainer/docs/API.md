# Placement Trainer API (v1)

A JSON REST API for the Placement Trainer app. It shares grading, ML analysis and career logic with the web pages, so results match what students see in the browser.

Base URL: `http://<host>:5000/api/v1`

## Conventions

- Request and response bodies are JSON. Send `Content-Type: application/json` on POST and PUT.
- Errors return a JSON object: `{"error": "message"}` with an HTTP status code.
- Common status codes: `400` bad input, `401` missing or invalid token, `404` not found or not yours, `409` conflict (for example, the daily test is already done).
- Users see only their own data. Admin-only actions are not part of this API. Use the web Career admin page.

## Authentication

Log in once to get a token, then send it on every other request:

```
Authorization: Bearer <token>
```

Tokens are random strings. The server stores only their SHA-256 hashes. A token stays valid until you call logout.

### POST /auth/login

Request:

```json
{"email": "sam@example.com", "password": "secret1"}
```

Response `201`:

```json
{"token": "k3Q...", "user": {"id": 2, "name": "Sam", "email": "sam@example.com", "role": "student"}}
```

Errors: `401` with `{"error": "invalid email or password"}`.

### POST /auth/logout

Revokes the token that was sent. Response: `{"ok": true}`.

### GET /me

Returns the current user: `{"id", "name", "email", "role"}`.

## Performance analysis

### GET /me/analysis

Returns the ML performance analysis for the current user. Main fields:

- `answered`, `correct`, `raw_accuracy`, `summary`, `notes`
- `categories`: one object per aptitude category with `category`, `answered`, `correct`, `score`, `status`, `confidence`, `z`
- `strengths`, `weaknesses`, `untested`: category names
- `trend`, `predicted_next`: `null` until there is enough practice
- `recommendations`: list of strings
- `cluster`: peer profile, or `null` when there are too few students

## Practice questions and attempts

### GET /questions

Query parameters:

- `category`: `Mixed` (default) or one of the aptitude categories
- `count`: 1 to 20, default 10

Returns questions without correct answers:

```json
{"category": "Mixed", "questions": [
  {"id": 12, "text": "...", "options": ["...", "...", "...", "..."], "category": "Logical Reasoning", "difficulty": 2}
]}
```

### POST /attempts

Records a timed practice quiz. Response `201` with the score.

Request:

```json
{
  "category": "Mixed",
  "time_taken_seconds": 420,
  "answers": [
    {"question_id": 12, "selected": 1},
    {"question_id": 13, "selected": null}
  ]
}
```

- `selected` is 0 to 3, or `null` for a skipped question.
- `question_id` values must be unique within one request.

Response includes `attempt_id`, `score`, `total`, `percent` and a `results` list with `question_id`, `selected`, `correct`, `correct_option` and `explanation`.

### GET /attempts

Lists the user's attempts, newest first: `{"attempts": [{"id", "category", "score", "total", "time_taken", "created_at"}]}`.

## Daily test

A daily test is a fixed set of questions for each user and each day. It can be taken once per day and builds a streak. Questions focus on the user's weaker categories.

### GET /daily

```json
{"date": "2026-10-08", "completed": false, "attempt_id": null, "streak": 3, "count": 5,
 "questions": [{"id": 12, "text": "...", "options": ["..."], "category": "...", "difficulty": 2}]}
```

Once completed, `questions` is omitted and `attempt_id` is set.

### POST /daily/submit

Request: `{"answers": [{"question_id": 12, "selected": 1}, ...]}`, using the question ids from `GET /daily`.

Errors: `409` if today's test is already submitted. `400` if an answer does not belong to today's set.

Response `201`: same shape as `POST /attempts`.

## Mock interviews

Each interview has 3 to 5 questions. Each answer gets a score and label: "Strong" (75+), "Fair" (50 to 74) or "Needs work" (below 50). Answers are scored by keyword and concept coverage, with feedback on filler words and the STAR structure for behavioural answers. Scoring is heuristic and not AI-based.

Interview types: `HR`, `Behavioural`, `Technical`, or `Mixed` (questions from all types).

### POST /interviews

Request: `{"type": "Mixed", "count": 3}`. `count` is 3 to 5.

Response `201`: `{"session_id", "type", "items": [{"id", "position", "question", "interview_type", "answered"}]}`.

### GET /interviews

Lists the user's interview sessions: `{"interviews": [{"id", "interview_type", "total", "answered", "avg_score", "created_at"}]}`.

### GET /interviews/{session_id}

Returns the session with its `items` and `completed` flag.

### POST /interviews/{session_id}/items/{item_id}/answer

Request: `{"answer": "My answer text..."}`

Response:

```json
{"item_id": 31, "score": 72.5, "label": "Good", "hits": ["skill", "project"], "missed": ["goal"],
 "star": null, "filler_count": 1, "words": 48, "feedback": ["..."]}
```

- `star` is an object with `situation`, `task`, `action` and `result` booleans for behavioural questions, otherwise `null`.
- Errors: `404` if the item is not in this session. `409` if it was already answered.

### GET /interviews/{session_id}/report

Summary for a finished interview. Returns `409` with `"interview is not finished yet"` until every question is answered.

## Career

Career readiness combines aptitude and interview practice:

- Aptitude: average score across the aptitude categories linked to the chosen role. Untested categories count as 50.
- Interview: average of the user's interview session scores.
- Readiness = 0.7 × aptitude + 0.3 × interview. With no interview practice, readiness equals aptitude.
- Labels: 75 or more is "Ready to apply", 55 to 74 is "Getting there", below 55 is "Needs focused practice".

### GET /roles

Job roles with their description, linked aptitude categories and training topics:

```json
{"roles": [{"id": 1, "title": "Software Developer", "description": "...",
            "aptitude_categories": ["Quantitative Aptitude", "Logical Reasoning"],
            "topics": [{"topic": "Programming and DSA", "guidance": "..."}]}]}
```

### GET /companies

`{"companies": [{"id", "name", "sector"}]}`

### GET /companies/{company_id}

Company detail:

- `hiring_process`: short description
- `question_rounds`: previous-year questions grouped by round (`Aptitude`, `Coding`, `Technical`, `HR`). Each question has `question`, `year`, `source_url` and `source_note`.
- `alumni`: verified alumni who opted in. Each has `name`, `role_title`, `batch_year`, `phone` and `public_email`.

Errors: `404` if the company does not exist.

Questions are candidate-reported and each one carries its source. They are not checked against the company.

### GET /career/target

Returns the user's target, or `null`:

```json
{"target": {"role_id": 1, "role_title": "Software Developer", "company_id": 1,
            "company": "TCS", "position_title": "Associate Software Engineer"},
 "readiness": {"readiness": 58.0, "label": "Getting there", "aptitude": 58.0,
               "interview": null, "categories": ["Quantitative Aptitude", "Logical Reasoning"]}}
```

### PUT /career/target

Sets or replaces the target. Request:

```json
{"role_id": 1, "company_id": 1, "position_title": "Associate Software Engineer"}
```

- `role_id` is required and must be an integer.
- `company_id` is an integer, or `null` to use `company_name` (a company not in the list).
- `position_title` is free text.

Response: the same shape as `GET /career/target`. Errors: `400`.

### POST /alumni

Joins the alumni directory. The profile is listed only after an admin verifies it.

Request:

```json
{"company_id": 1, "role_title": "Associate Software Engineer", "batch_year": "2025",
 "phone": "9999999999", "public_email": "you@example.com", "consent": true}
```

- `consent` must be `true`. The API refuses the request without it.
- Editing a profile (sending `POST /alumni` again) resets it to unverified.

Response `201`: `{"ok": true, "verified": false, "note": "..."}`.

### DELETE /alumni

Removes the user's alumni profile. Response: `{"ok": true}`.

## Example session

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"sam@example.com","password":"secret1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s http://localhost:5000/api/v1/career/target -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:5000/api/v1/interviews -H "Authorization: Bearer $TOKEN"
```

## Security notes

- Tokens are bearer tokens. Use HTTPS in production, and do not put tokens in URLs.
- There is no rate limiting yet. Add it before exposing the API publicly.
- The default admin password (`admin123`) must be changed before any real use. Set `ADMIN_PASSWORD` before the first run.

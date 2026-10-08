"""Mock interview engine: question selection, answer scoring and feedback.

Scoring is rule-based and runs locally (no API key needed):
  content   (50%) - share of the expected concepts the answer covers
  length    (20%) - enough detail without rambling (about 40 to 180 words)
  structure (30%) - STAR cues for behavioural questions, or 3+ sentences otherwise
  penalty         - up to 15 points off for filler words ("um", "basically", ...)
"""
import random
import re

from interview_data import TYPES

SECONDS_PER_ANSWER = 120

TIPS = {
    "HR": "Answer in about 60 to 90 seconds. Go past, present, future.",
    "Behavioural": "Use STAR: Situation, Task, Action (what you did), Result (what changed).",
    "Technical": "Define the concept first, then give one example or a real use case.",
}

FILLER_WORDS = ["um", "uh", "umm", "basically", "actually", "you know",
                "so yeah", "i guess", "kind of", "sort of"]

STAR_PATTERNS = {
    "Situation": r"\b(when|during|once|while|at my|in my|last year|at college)\b",
    "Task": r"\b(my role|responsible|my goal|needed to|had to|asked to|my task|objective)\b",
    "Action": r"\b(i decided|i built|i created|i led|i planned|i organi[sz]ed|i wrote|"
              r"i implemented|i took|i started|i helped|i worked|i designed|i resolved|"
              r"i fixed|i learned|i researched|i practi[sc]ed)\b",
    "Result": r"\b(result|resulted|outcome|improved|delivered|achieved|finished|success|"
              r"successfully|reduced|increased|learned)\b|\d+\s?%",
}


def _concept_pattern(concept):
    """Regex for one expected concept.

    Phrases must appear as written. Single words match by stem: the first
    max(4, len - 3) letters, so "decided" matches "decision" and "learning" matches "learned".
    """
    c = concept.lower()
    if " " in c:
        return r"\b" + re.escape(c)
    return r"\b" + re.escape(c[:max(4, len(c) - 3)])


def label(score):
    if score >= 75:
        return "Strong"
    if score >= 50:
        return "Fair"
    return "Needs work"


def _words(text):
    return re.findall(r"[A-Za-z0-9%']+", text)


def _length_score(n):
    if n == 0:
        return 0.0
    if n < 15:
        return 0.5 * n / 15
    if n < 40:
        return 0.75
    if n <= 180:
        return 1.0
    return max(0.4, 1 - (n - 180) / 200)


def _feedback(words, sentences, missed, fillers, star, itype):
    if words == 0:
        return ["No answer recorded. Type or dictate an answer, then submit."]
    tips = []
    if missed:
        tips.append("Cover these points: " + ", ".join(missed[:4]) + ".")
    if words < 40:
        tips.append(f"Too brief ({words} words). Aim for 40 to 180 words and include one concrete example.")
    elif words > 180:
        tips.append(f"Too long ({words} words). Keep it under about 3 minutes of speaking.")
    if star is not None:
        lacking = [k for k, ok in star.items() if not ok]
        if lacking:
            tips.append("Missing STAR parts: " + ", ".join(lacking) + ".")
        else:
            tips.append("Good STAR structure: situation, task, action and result are all there.")
    elif sentences < 3:
        tips.append("Use at least three full sentences so your point is clear.")
    if fillers:
        total = sum(c for _, c in fillers)
        tips.append("Remove filler words: " + ", ".join(f for f, _ in fillers) + f" ({total} found).")
    if not tips:
        tips.append("Strong answer. It is clear, complete and concise.")
    return tips


def score_answer(answer, itype, keywords_csv):
    """Score one spoken or typed answer. Returns a dict with score, feedback and details."""
    text = (answer or "").strip()
    low = text.lower()
    words = len(_words(text))
    keywords = [k.strip().lower() for k in keywords_csv.split(",") if k.strip()]

    hits = [k for k in keywords if re.search(_concept_pattern(k), low)]
    missed = [k for k in keywords if k not in hits]
    coverage = len(hits) / len(keywords) if keywords else 1.0

    fillers = []
    for f in FILLER_WORDS:
        c = len(re.findall(r"\b" + re.escape(f) + r"\b", low))
        if c:
            fillers.append((f, c))
    filler_count = sum(c for _, c in fillers)

    sentences = len([p for p in re.split(r"[.!?]+", text) if p.strip()])
    star = None
    if itype == "Behavioural":
        star = {k: bool(re.search(p, low)) for k, p in STAR_PATTERNS.items()}
        structure = sum(star.values()) / len(STAR_PATTERNS)
    else:
        structure = min(1.0, sentences / 3)

    raw = 0.5 * coverage + 0.2 * _length_score(words) + 0.3 * structure
    score = max(0.0, min(100.0, 100 * raw - min(15, 3 * filler_count)))
    if words == 0:
        score = 0.0

    return {
        "score": round(score, 1),
        "label": label(score),
        "words": words,
        "hits": hits,
        "missed": missed,
        "filler_count": filler_count,
        "star": star,
        "feedback": _feedback(words, sentences, missed, fillers, star, itype),
    }


def pick_questions(conn, itype, count):
    """Choose question ids. 'Mixed' rotates across HR, Behavioural and Technical."""
    pools = {}
    for r in conn.execute("SELECT id, interview_type FROM interview_questions"):
        pools.setdefault(r["interview_type"], []).append(r["id"])
    types = list(TYPES) if itype == "Mixed" else [itype]
    types = [t for t in types if pools.get(t)]
    for t in types:
        random.shuffle(pools[t])

    picked = []
    i = 0
    while len(picked) < count and any(pools.get(t) for t in types):
        t = types[i % len(types)]
        if pools.get(t):
            picked.append(pools[t].pop())
        i += 1
    return picked


def sessions_summary(conn, user_id):
    """One row per interview session with answered count and average score."""
    return conn.execute(
        """SELECT s.id, s.interview_type, s.created_at,
                  COUNT(i.id) AS total,
                  COUNT(i.answer) AS answered,
                  ROUND(AVG(i.score), 1) AS avg_score
           FROM interview_sessions s
           JOIN interview_items i ON i.session_id = s.id
           WHERE s.user_id = ?
           GROUP BY s.id
           ORDER BY s.id DESC""", (user_id,)).fetchall()

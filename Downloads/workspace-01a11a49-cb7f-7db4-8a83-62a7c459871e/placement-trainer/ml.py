"""
Performance analysis for the placement trainer.

Pipeline (scikit-learn + numpy, runs locally, no external API):
  1. Bayesian-smoothed accuracy per category. A student with 2 out of 2 correct
     should not be scored as "perfect", so each category is pulled toward 50%
     until there is enough evidence.
  2. Peer z-score per category. Compares a student with every other student
     who answered questions in that category.
  3. KMeans clustering of students' category-accuracy vectors. Groups students
     into learning profiles (e.g. "Strong in Verbal, needs work in Quant").
  4. Linear regression on the score history. Gives the improvement trend and
     an estimate of the next score.
  5. A rule layer that turns these numbers into strengths, weaknesses and
     recommendations.
"""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression

PRIOR = 0.5          # neutral starting accuracy
PRIOR_WEIGHT = 2     # strength of the prior, in pseudo-answers
STRONG_T = 0.70      # smoothed accuracy at or above this is a strength
WEAK_T = 0.45        # smoothed accuracy at or below this is a weakness
WEAK_Z = -1.0        # or a peer z-score at or below this
MIN_PEERS = 3        # minimum other students needed for a z-score
MIN_CLUSTER_USERS = 3
RELIABLE_ANSWERS = 15


def _smoothed(correct, total):
    return (correct + PRIOR * PRIOR_WEIGHT) / (total + PRIOR_WEIGHT)


def _confidence(total):
    if total < 5:
        return "low"
    if total < RELIABLE_ANSWERS:
        return "medium"
    return "high"


def _load(conn):
    """Return (category list, {(user_id, category): (correct, total)})."""
    cats = [r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM questions ORDER BY category")]
    rows = conn.execute(
        """SELECT user_id, category, SUM(is_correct) AS correct, COUNT(*) AS total
           FROM attempt_answers GROUP BY user_id, category""").fetchall()
    stats = {(r["user_id"], r["category"]): (r["correct"], r["total"]) for r in rows}
    return cats, stats


def _peer_z(stats, category, user_id, acc):
    """Z-score of a smoothed accuracy against other students in the same category."""
    peers = [_smoothed(c, t) for (u, cat), (c, t) in stats.items()
             if cat == category and u != user_id]
    if len(peers) < MIN_PEERS:
        return None
    std = float(np.std(peers))
    if std == 0:
        return None
    return (acc - float(np.mean(peers))) / std


def _history(conn, user_id):
    rows = conn.execute(
        "SELECT score, total FROM attempts WHERE user_id = ? ORDER BY created_at, id",
        (user_id,)).fetchall()
    return [100.0 * r["score"] / r["total"] for r in rows if r["total"]]


def _trend(history):
    """Fit a line through the score history. Returns (trend label, predicted next score)."""
    if len(history) < 3:
        return None, None
    X = np.arange(len(history)).reshape(-1, 1)
    y = np.array(history)
    model = LinearRegression().fit(X, y)
    slope = float(model.coef_[0])
    predicted = float(np.clip(model.predict([[len(history)]])[0], 0, 100))
    if slope > 1:
        label = "improving"
    elif slope < -1:
        label = "declining"
    else:
        label = "steady"
    return label, round(predicted, 1)


def _cluster_profile(cats, stats, user_id):
    """KMeans over all active students. Returns the profile of the given student."""
    active = sorted({u for (u, _) in stats})
    if user_id not in active or len(active) < MIN_CLUSTER_USERS:
        return None
    X = np.array([[_smoothed(*stats.get((u, c), (0, 0))) for c in cats] for u in active])
    k = min(3, len(active))
    model = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
    label = int(model.labels_[active.index(user_id)])
    centroid = model.cluster_centers_[label]
    if centroid.max() - centroid.min() < 0.08:
        name = "Balanced all-rounder"
    else:
        best = cats[int(np.argmax(centroid))]
        worst = cats[int(np.argmin(centroid))]
        name = f"Strong in {best}, needs work in {worst}"
    return {
        "name": name,
        "group_size": int((model.labels_ == label).sum()),
        "students_compared": len(active),
        "clusters": k,
    }


def analyze_user(conn, user_id):
    """Full performance analysis for one student."""
    cats, stats = _load(conn)

    reports = []
    for c in cats:
        correct, total = stats.get((user_id, c), (0, 0))
        acc = _smoothed(correct, total)
        z = _peer_z(stats, c, user_id, acc) if total else None
        if total == 0:
            status = "untested"
        elif acc >= STRONG_T and (z is None or z >= 0):
            status = "strong"
        elif acc <= WEAK_T or (z is not None and z <= WEAK_Z):
            status = "weak"
        else:
            status = "developing"
        reports.append({
            "category": c,
            "answered": total,
            "correct": correct,
            "raw_accuracy": round(100.0 * correct / total, 1) if total else None,
            "score": round(100.0 * acc, 1),
            "z": None if z is None else round(z, 2),
            "confidence": _confidence(total),
            "status": status,
        })

    answered = sum(r["answered"] for r in reports)
    correct = sum(r["correct"] for r in reports)
    tested = [r for r in reports if r["answered"] > 0]
    strengths = sorted([r for r in tested if r["status"] == "strong"], key=lambda r: -r["score"])
    weaknesses = sorted([r for r in tested if r["status"] == "weak"], key=lambda r: r["score"])
    developing = [r for r in tested if r["status"] == "developing"]
    untested = [r["category"] for r in reports if r["status"] == "untested"]

    recs = []
    for r in weaknesses:
        recs.append(f"Practise {r['category']} daily. Start with level-1 questions and read every explanation.")
    for r in developing:
        recs.append(f"Push {r['category']} towards strong with level-2 and level-3 questions.")
    for c in untested:
        recs.append(f"Take a {c} quiz to get a baseline.")

    history = _history(conn, user_id)
    trend, predicted = _trend(history)
    cluster = _cluster_profile(cats, stats, user_id)

    if answered == 0:
        summary = "No data yet. Take your first quiz to unlock your analysis."
    else:
        parts = []
        if strengths:
            parts.append("strongest in " + ", ".join(r["category"] for r in strengths))
        if weaknesses:
            parts.append("needs work in " + ", ".join(r["category"] for r in weaknesses))
        summary = "; ".join(parts).capitalize() + "." if parts else \
            "Performance is developing evenly across all categories."

    notes = []
    if 0 < answered < 20:
        notes.append(f"Based on only {answered} answers so far. Results become reliable after about "
                     f"{RELIABLE_ANSWERS} answers per category.")
    if cluster is None:
        notes.append("Peer comparison and learning-profile clustering need at least "
                     f"{MIN_CLUSTER_USERS} active students.")

    return {
        "answered": answered,
        "correct": correct,
        "raw_accuracy": round(100.0 * correct / answered, 1) if answered else None,
        "categories": reports,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "untested": untested,
        "recommendations": recs,
        "trend": trend,
        "predicted_next": predicted,
        "cluster": cluster,
        "summary": summary,
        "notes": notes,
    }


def cohort_summary(conn):
    """Average accuracy per category across all students (for the admin view)."""
    rows = conn.execute(
        """SELECT category, COUNT(*) AS answered, SUM(is_correct) AS correct
           FROM attempt_answers GROUP BY category ORDER BY category""").fetchall()
    return [{
        "category": r["category"],
        "answered": r["answered"],
        "accuracy": round(100.0 * r["correct"] / r["answered"], 1),
    } for r in rows]

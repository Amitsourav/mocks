"""Deterministic learning analytics — no AI required.

These functions turn raw response data (correctness, time, difficulty) into the
diagnostic signals the dashboard and the AI narrative both build on:
  - error-typing (careless vs conceptual vs guess) from time × correctness × difficulty
  - concept mastery with forgetting-curve decay
  - behavioral metrics per attempt (guess rate, negative-marking loss, pacing)

Grounded in: error analysis (Baker/Corbett contextual slip), Bayesian Knowledge
Tracing (mastery), and the Ebbinghaus forgetting curve (decay).
"""

from __future__ import annotations

import math

# Time thresholds are RELATIVE to a reference (cohort/section median), so "fast"
# and "slow" adapt to item difficulty instead of using absolute seconds.
FAST_RATIO = 0.55
SLOW_RATIO = 1.35


def classify_error(
    is_correct: bool | None,
    time_ms: int | None,
    difficulty: str | None,
    median_ms: float | None,
) -> str:
    """Return an error_type: correct | careless | conceptual | guess | unattempted.

    - unattempted: no answer.
    - guess: correct, but fast on a HARD item (luck, not mastery).
    - careless: wrong but fast (knew it, rushed / trap option).
    - conceptual: wrong and not-fast (engaged but couldn't derive).
    """
    if is_correct is None:
        return "unattempted"

    fast = time_ms is not None and median_ms and time_ms < FAST_RATIO * median_ms
    slow = time_ms is not None and median_ms and time_ms > SLOW_RATIO * median_ms  # noqa: F841

    if is_correct:
        if fast and (difficulty or "").lower() == "hard":
            return "guess"
        return "correct"
    # wrong
    if fast:
        return "careless"
    return "conceptual"


def decay_retention(p_mastery: float, days_since_correct: float | None, half_life_days: float = 10.0) -> float:
    """Forgetting curve: mastery decays exponentially since last correct recall.

    retention = p_mastery * 2^(-days / half_life). No time info -> no decay.
    """
    if days_since_correct is None or days_since_correct <= 0:
        return round(p_mastery, 3)
    factor = math.pow(2.0, -days_since_correct / half_life_days)
    return round(p_mastery * factor, 3)


def gap_priority(retention: float, exam_weight: float = 1.0, recency: float = 1.0) -> float:
    """What to fix next: bigger gap × higher exam weight × more recent evidence."""
    return round((1.0 - retention) * exam_weight * recency, 3)


def bkt_posterior(prior: float, is_correct: bool, p_transit: float = 0.15,
                  p_guess: float = 0.22, p_slip: float = 0.10) -> float:
    """One Bayesian Knowledge Tracing update of P(mastered) after an observation.

    MCQ guess rate ~0.22 (4 options minus some distractor pull); slip ~0.10.
    """
    if is_correct:
        num = prior * (1 - p_slip)
        den = num + (1 - prior) * p_guess
    else:
        num = prior * p_slip
        den = num + (1 - prior) * (1 - p_guess)
    posterior = num / den if den else prior
    # transition: chance the unmastered part became mastered this opportunity
    posterior = posterior + (1 - posterior) * p_transit
    return min(0.999, max(0.001, posterior))


def attempt_behavior(question_rows: list[dict], neg_mark_per_wrong: float = 0.25) -> dict:
    """Aggregate behavioral metrics for one attempt from its question rows.

    Each row: {is_correct, error_type, time_spent_ms}. Returns guess_rate,
    negative_marking_loss, careless_share, avg_time_ms, and a coarse archetype.
    """
    n = len(question_rows) or 1
    wrong = sum(1 for r in question_rows if r.get("is_correct") is False)
    guesses = sum(1 for r in question_rows if r.get("error_type") == "guess")
    careless = sum(1 for r in question_rows if r.get("error_type") == "careless")
    times = [r["time_spent_ms"] for r in question_rows if r.get("time_spent_ms") is not None]
    avg_time = round(sum(times) / len(times)) if times else None

    guess_rate = round(100 * guesses / n, 2)
    careless_share = round(100 * careless / max(1, wrong), 2)
    neg_loss = round(wrong * neg_mark_per_wrong, 2)

    if careless_share >= 50:
        archetype = "Rusher"          # many fast-wrong: knows it, hurries
    elif guess_rate >= 20:
        archetype = "Gambler"         # over-guesses on hard items
    elif avg_time and times and max(times) > 3 * (avg_time or 1):
        archetype = "Jumping Around"  # very uneven pacing
    else:
        archetype = "Marathoner"      # steady

    return {
        "guess_rate": guess_rate,
        "negative_marking_loss": neg_loss,
        "careless_share": careless_share,
        "avg_time_ms": avg_time,
        "behavior_archetype": archetype,
    }

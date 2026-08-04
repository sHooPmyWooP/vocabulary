"""Pure aggregation over entries and review-log rows.

No I/O. Fed the data the store retrieves, it computes the numbers the stats
screen shows: total words, due-today count, maturity breakdown, a
reviews-per-day series for a trailing window, and the accuracy rate.

Inputs are duck-typed: entries expose ``interval``, ``repetitions`` and
``due_date``; reviews expose ``graded_at`` and ``grade``. Both attribute
access (dataclasses) and item access (sqlite ``Row``/dicts) are supported so
callers can pass store objects straight through.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from app.scheduler import MATURE_INTERVAL

# Grades that count as a successful recall for the accuracy rate.
CORRECT_GRADES = frozenset({"good", "easy"})


@dataclass(frozen=True)
class DayCount:
    """One day of the reviews-per-day series."""

    date: str  # ISO (YYYY-MM-DD)
    count: int


@dataclass(frozen=True)
class Maturity:
    """Maturity breakdown of the vocabulary deck."""

    new: int      # never reviewed
    learning: int  # reviewed, interval < 21 days
    mature: int    # interval >= 21 days


@dataclass(frozen=True)
class Stats:
    """Everything the stats screen renders."""

    total_words: int
    due_today: int
    maturity: Maturity
    reviews_per_day: list[DayCount]
    accuracy: float  # percent, 0..100, one decimal


def _get(obj: Any, key: str) -> Any:
    """Read ``key`` from a dataclass (attr) or a Row/dict (item)."""
    try:
        return obj[key]
    except (TypeError, KeyError, IndexError):
        return getattr(obj, key)


def _classify(interval: int, repetitions: int) -> str:
    if repetitions == 0:
        return "new"
    if interval >= MATURE_INTERVAL:
        return "mature"
    return "learning"


def compute(
    entries: Iterable[Any],
    reviews: Iterable[Any],
    *,
    today: date,
    days: int = 30,
) -> Stats:
    """Aggregate ``entries`` and ``reviews`` into a :class:`Stats`."""
    entries = list(entries)
    total_words = len(entries)

    today_iso = today.isoformat()
    due_today = 0
    buckets = Counter()
    for e in entries:
        interval = int(_get(e, "interval"))
        repetitions = int(_get(e, "repetitions"))
        due_date = str(_get(e, "due_date"))
        if due_date <= today_iso:
            due_today += 1
        buckets[_classify(interval, repetitions)] += 1

    maturity = Maturity(
        new=buckets["new"],
        learning=buckets["learning"],
        mature=buckets["mature"],
    )

    # Trailing window of ``days`` ending today (inclusive), oldest first.
    window = [today - timedelta(days=days - 1 - i) for i in range(days)]
    window_iso = {d.isoformat() for d in window}

    per_day = Counter()
    correct = 0
    total_reviews = 0
    for r in reviews:
        grade = str(_get(r, "grade"))
        day = str(_get(r, "graded_at"))[:10]
        total_reviews += 1
        if grade in CORRECT_GRADES:
            correct += 1
        if day in window_iso:
            per_day[day] += 1

    reviews_per_day = [DayCount(d.isoformat(), per_day[d.isoformat()]) for d in window]

    accuracy = round(correct / total_reviews * 100, 1) if total_reviews else 0.0

    return Stats(
        total_words=total_words,
        due_today=due_today,
        maturity=maturity,
        reviews_per_day=reviews_per_day,
        accuracy=accuracy,
    )

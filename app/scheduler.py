"""SM-2 spaced-repetition scheduler.

Pure module, no I/O. Given a card's scheduling state (ease factor, interval,
repetitions) and a grade, it computes the new scheduling state and the next
due date. This is the classic SuperMemo SM-2 algorithm with a four-button
grade front-end (Again / Hard / Good / Easy).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Four review buttons mapped to SM-2 recall-quality scores (0..5).
GRADE_QUALITY: dict[str, int] = {
    "again": 0,
    "hard": 3,
    "good": 4,
    "easy": 5,
}

MIN_EASE = 1.3
# Interval (days) at/above which a card is considered mature (see PRD).
MATURE_INTERVAL = 21


@dataclass(frozen=True)
class SchedulingState:
    """The SM-2 fields carried by a card between reviews."""

    ease_factor: float = 2.5
    interval: int = 0
    repetitions: int = 0


@dataclass(frozen=True)
class Scheduled:
    """Result of grading a card: the new state plus the next due date."""

    ease_factor: float
    interval: int
    repetitions: int
    due_date: date
    state: str


def _maturity(interval: int) -> str:
    return "mature" if interval >= MATURE_INTERVAL else "learning"


def schedule(state: SchedulingState, grade: str, *, today: date) -> Scheduled:
    """Apply SM-2 for ``grade`` and return the new state and due date.

    A grade of "again" (quality < 3) lapses the card: repetitions reset to 0
    and the interval collapses to 1 day. Higher grades advance the interval
    (1 -> 6 -> interval * ease). The ease factor is adjusted after every
    review and floored at ``MIN_EASE``.
    """
    if grade not in GRADE_QUALITY:
        raise ValueError(f"unknown grade: {grade!r}")
    q = GRADE_QUALITY[grade]

    ease = state.ease_factor
    interval = state.interval
    reps = state.repetitions

    if q < 3:
        reps = 0
        interval = 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        reps += 1

    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if ease < MIN_EASE:
        ease = MIN_EASE

    return Scheduled(
        ease_factor=ease,
        interval=interval,
        repetitions=reps,
        due_date=today + timedelta(days=interval),
        state=_maturity(interval),
    )

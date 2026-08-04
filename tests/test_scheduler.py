"""Tests for the pure SM-2 scheduler."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.scheduler import SchedulingState, schedule

TODAY = date(2024, 1, 1)


def test_first_review_good_sets_interval_one_day():
    result = schedule(SchedulingState(), "good", today=TODAY)

    assert result.interval == 1
    assert result.repetitions == 1
    assert result.due_date == TODAY + timedelta(days=1)
    assert result.state == "learning"
    # Good keeps the default ease factor unchanged.
    assert result.ease_factor == pytest.approx(2.5)


def test_second_good_review_jumps_to_six_days():
    after_first = schedule(SchedulingState(), "good", today=TODAY)
    state = SchedulingState(
        ease_factor=after_first.ease_factor,
        interval=after_first.interval,
        repetitions=after_first.repetitions,
    )
    result = schedule(state, "good", today=TODAY)

    assert result.interval == 6
    assert result.repetitions == 2


def test_third_good_review_multiplies_by_ease():
    state = SchedulingState(ease_factor=2.5, interval=6, repetitions=2)
    result = schedule(state, "good", today=TODAY)

    # round(6 * 2.5) == 15
    assert result.interval == 15
    assert result.repetitions == 3


def test_easy_raises_ease_factor():
    result = schedule(SchedulingState(), "easy", today=TODAY)
    assert result.ease_factor == pytest.approx(2.6)


def test_hard_lowers_ease_factor():
    result = schedule(SchedulingState(), "hard", today=TODAY)
    assert result.ease_factor == pytest.approx(2.36)


def test_again_lapse_resets_progress():
    state = SchedulingState(ease_factor=2.5, interval=15, repetitions=3)
    result = schedule(state, "again", today=TODAY)

    assert result.repetitions == 0
    assert result.interval == 1
    assert result.due_date == TODAY + timedelta(days=1)
    # Ease factor drops steeply and is floored at the minimum.
    assert result.ease_factor == pytest.approx(1.7)


def test_ease_factor_never_drops_below_minimum():
    state = SchedulingState(ease_factor=1.3, interval=1, repetitions=0)
    result = schedule(state, "again", today=TODAY)
    assert result.ease_factor == pytest.approx(1.3)


def test_boundary_interval_marks_card_mature():
    # interval of 20 * ease 1.05 rounds to 21 -> mature threshold.
    state = SchedulingState(ease_factor=1.05, interval=20, repetitions=2)
    result = schedule(state, "good", today=TODAY)
    assert result.interval == 21
    assert result.state == "mature"


def test_just_below_boundary_is_learning():
    state = SchedulingState(ease_factor=1.0, interval=20, repetitions=2)
    result = schedule(state, "good", today=TODAY)
    assert result.interval == 20
    assert result.state == "learning"


def test_unknown_grade_rejected():
    with pytest.raises(ValueError):
        schedule(SchedulingState(), "meh", today=TODAY)

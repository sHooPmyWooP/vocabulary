"""Unit tests for the pure stats aggregation module.

Fed fixed sets of entries and review-log rows; asserts the computed totals,
maturity buckets, per-day series and accuracy rate. No I/O.
"""
from __future__ import annotations

from datetime import date

from app import stats


def _entry(interval: int, repetitions: int, due_date: str) -> dict:
    """Minimal entry-shaped input (only the fields stats reads)."""
    return {"interval": interval, "repetitions": repetitions, "due_date": due_date}


def _review(graded_at: str, grade: str) -> dict:
    return {"graded_at": graded_at, "grade": grade}


TODAY = date(2024, 6, 15)


def test_total_words_counts_every_entry():
    entries = [_entry(0, 0, "2024-06-15"), _entry(6, 2, "2024-06-20")]
    result = stats.compute(entries, [], today=TODAY)
    assert result.total_words == 2


def test_total_words_zero_state():
    result = stats.compute([], [], today=TODAY)
    assert result.total_words == 0
    assert result.due_today == 0
    assert result.accuracy == 0.0


def test_due_today_counts_cards_due_on_or_before_today():
    entries = [
        _entry(0, 0, "2024-06-10"),  # overdue -> due
        _entry(1, 1, "2024-06-15"),  # due exactly today -> due
        _entry(6, 2, "2024-06-20"),  # future -> not due
    ]
    result = stats.compute(entries, [], today=TODAY)
    assert result.due_today == 2


def test_maturity_buckets_new_learning_mature():
    entries = [
        _entry(0, 0, "2024-06-15"),   # never reviewed -> new
        _entry(1, 1, "2024-06-16"),   # reviewed, interval < 21 -> learning
        _entry(6, 2, "2024-06-21"),   # reviewed, interval < 21 -> learning
        _entry(21, 3, "2024-07-06"),  # interval >= 21 -> mature
        _entry(40, 4, "2024-07-25"),  # interval >= 21 -> mature
    ]
    result = stats.compute(entries, [], today=TODAY)
    assert result.maturity.new == 1
    assert result.maturity.learning == 2
    assert result.maturity.mature == 2


def test_reviews_per_day_series_length_and_order():
    result = stats.compute([], [], today=TODAY, days=30)
    series = result.reviews_per_day
    assert len(series) == 30
    # Oldest first, ending today.
    assert series[0].date == "2024-05-17"
    assert series[-1].date == "2024-06-15"
    assert all(d.count == 0 for d in series)


def test_reviews_per_day_counts_by_day():
    reviews = [
        _review("2024-06-15T08:00:00+00:00", "good"),
        _review("2024-06-15T09:30:00+00:00", "again"),
        _review("2024-06-14T20:00:00+00:00", "easy"),
        _review("2024-04-01T10:00:00+00:00", "good"),  # outside 30-day window
    ]
    result = stats.compute([], reviews, today=TODAY, days=30)
    by_date = {d.date: d.count for d in result.reviews_per_day}
    assert by_date["2024-06-15"] == 2
    assert by_date["2024-06-14"] == 1
    # Outside the window is not present in the series at all.
    assert "2024-04-01" not in by_date


def test_accuracy_percent_good_plus_easy():
    reviews = [
        _review("2024-06-15T08:00:00+00:00", "good"),
        _review("2024-06-15T08:00:00+00:00", "easy"),
        _review("2024-06-15T08:00:00+00:00", "hard"),
        _review("2024-06-15T08:00:00+00:00", "again"),
    ]
    result = stats.compute([], reviews, today=TODAY)
    assert result.accuracy == 50.0


def test_accuracy_rounds_to_one_decimal():
    reviews = [
        _review("2024-06-15T08:00:00+00:00", "good"),
        _review("2024-06-15T08:00:00+00:00", "again"),
        _review("2024-06-15T08:00:00+00:00", "again"),
    ]
    result = stats.compute([], reviews, today=TODAY)
    assert result.accuracy == 33.3

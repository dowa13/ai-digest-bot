"""Topic trend tracking — count topic frequency across the user's recent items.

A topic is considered "trending" if it appears in ≥ TREND_MIN_OCCURRENCES
processed items in the last TREND_WINDOW_DAYS.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.shared.db import list_processed_items_window

TREND_WINDOW_DAYS = 28
TREND_MIN_OCCURRENCES = 3


def topic_counts(user_id: UUID, days: int = TREND_WINDOW_DAYS) -> Counter[str]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = list_processed_items_window(user_id, since=since, include_noise=False)
    c: Counter[str] = Counter()
    for r in rows:
        for t in r.get("topics") or []:
            c[t] += 1
    return c


def trending_topics(user_id: UUID, days: int = TREND_WINDOW_DAYS) -> set[str]:
    counts = topic_counts(user_id, days)
    return {t for t, n in counts.items() if n >= TREND_MIN_OCCURRENCES}


def topic_delta(
    user_id: UUID, days: int = 7, prev_days: int = 7
) -> dict[str, tuple[int, int]]:
    """Return {topic: (count_this_period, count_prev_period)}."""
    now = datetime.now(UTC)
    this_since = now - timedelta(days=days)
    prev_since = now - timedelta(days=days + prev_days)
    prev_until = this_since

    this_rows = list_processed_items_window(user_id, since=this_since, include_noise=False)
    prev_rows = list_processed_items_window(
        user_id, since=prev_since, until=prev_until, include_noise=False
    )

    this_counts: Counter[str] = Counter()
    prev_counts: Counter[str] = Counter()
    for r in this_rows:
        for t in r.get("topics") or []:
            this_counts[t] += 1
    for r in prev_rows:
        for t in r.get("topics") or []:
            prev_counts[t] += 1

    all_topics = set(this_counts) | set(prev_counts)
    return {t: (this_counts[t], prev_counts[t]) for t in all_topics}

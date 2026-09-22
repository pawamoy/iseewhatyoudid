"""Tests for activity aggregation."""

from __future__ import annotations

from datetime import datetime, timezone

from iseewhatyoudid._internal.activity import _ActivityEvent, _aggregate_activity


def test_aggregate_activity_includes_comments_and_year_heatmap() -> None:
    """Comments contribute to every applicable bucket and the daily grid."""
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    comment = datetime(2026, 8, 14, 10, tzinfo=timezone.utc)

    aggregated = _aggregate_activity(
        [
            _ActivityEvent(
                category="comments",
                occurred_at=comment,
                repository="octocat/example",
            )
        ],
        now=now,
    )

    assert len(aggregated["days_last_365"]) == 365
    assert aggregated["days_last_365"][-1].label == "2026-08-15"
    yesterday = next(
        bucket for bucket in aggregated["days_last_365"] if bucket.label == "2026-08-14"
    )
    assert yesterday.counts["comments"] == 1
    august = next(
        bucket for bucket in aggregated["months_last_12"] if bucket.label == "2026-08"
    )
    assert august.counts["comments"] == 1

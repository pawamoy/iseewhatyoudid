# SPDX-License-Identifier: ISC
#
# ISC License
#
# Copyright (c) 2026, Timothée Mazzucotelli and contributors
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""Tests for activity aggregation."""

from __future__ import annotations

from datetime import UTC, datetime

from iseewhatyoudid._internal.activity import _ActivityEvent, _aggregate_activity


def test_aggregate_activity_includes_comments_and_year_heatmap() -> None:
    """Comments contribute to every applicable bucket and the daily grid."""
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    comment = datetime(2026, 8, 14, 10, tzinfo=UTC)

    aggregated = _aggregate_activity(
        [
            _ActivityEvent(
                category="comments",
                occurred_at=comment,
                repository="octocat/example",
            ),
        ],
        now=now,
    )

    assert len(aggregated["days_last_365"]) == 365
    assert aggregated["days_last_365"][-1].label == "2026-08-15"
    yesterday = next(bucket for bucket in aggregated["days_last_365"] if bucket.label == "2026-08-14")
    assert yesterday.counts["comments"] == 1
    august = next(bucket for bucket in aggregated["months_last_12"] if bucket.label == "2026-08")
    assert august.counts["comments"] == 1

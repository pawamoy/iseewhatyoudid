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

"""Tests for HTML dashboard rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from iseewhatyoudid._internal.activity import (
    _ActivityEvent,
    _aggregate_activity,
    _Bucket,
    _CommitSummary,
)
from iseewhatyoudid._internal.html_render import _dashboard_data, _write_dashboard_html

if TYPE_CHECKING:
    from pathlib import Path


def test_write_dashboard_html(tmp_path: Path) -> None:
    """The HTML report contains Chart.js and serialized dashboard data."""
    path = tmp_path / "activity.html"
    aggregated = {
        "years": [_Bucket(label="2026", counts={"opened_issues": 2})],
        "months_last_12": [],
        "weeks_last_12": [],
        "days_last_30": [],
        "days_last_365": [_Bucket(label="2026-01-01", counts={"comments": 3})],
    }
    events = [
        _ActivityEvent(
            category="opened_issues",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            count=2,
            title="A useful issue",
            url="https://github.com/octocat/example/issues/1",
        ),
        _ActivityEvent(
            category="comments",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            count=3,
        ),
    ]
    commits = [
        _CommitSummary(
            oid="abc123",
            headline="docs(readme): explain the dashboard",
            committed_at=datetime(2026, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            url="https://github.com/octocat/example/commit/abc123",
        ),
    ]

    _write_dashboard_html(
        aggregated=aggregated,
        events=events,
        commits=commits,
        user="octo<script>",
        scope=["all repositories"],
        path=path,
    )

    content = path.read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/chart.js" in content
    assert "Your GitHub story — octo&lt;script&gt;" in content
    assert '"label":"Opened issues"' in content
    assert '"data":[2]' in content
    assert '"label":"Comments"' in content
    assert '"date":"2026-01-01","count":3' in content
    assert "Your work adds up" in content
    assert "Rediscover something you did" in content
    assert '"commitAnalysis":{"available":true' in content
    assert "What kinds of work did your commits hold?" in content
    assert "Commit-summary gallery" in content


def test_dashboard_summaries_include_totals_and_averages() -> None:
    """Global cards summarize all-time totals and recent averages."""
    aggregated = {
        "years": [
            _Bucket(label="2025", counts={"opened_issues": 2, "closed_issues": 1}),
            _Bucket(label="2026", counts={"opened_issues": 4, "closed_issues": 3}),
        ],
        "months_last_12": [
            _Bucket(label="2026-07", counts={"opened_issues": 2}),
            _Bucket(label="2026-08", counts={"opened_issues": 4}),
        ],
        "weeks_last_12": [],
        "days_last_30": [],
        "days_last_365": [],
    }
    events = [
        _ActivityEvent(
            category="opened_issues",
            occurred_at=datetime(2025, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            count=6,
        ),
        _ActivityEvent(
            category="closed_issues",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            count=4,
        ),
    ]

    data = _dashboard_data(
        aggregated=aggregated,
        events=events,
        commits=[],
        user="octocat",
        scope=["all repositories"],
    )

    opened_issues = next(summary for summary in data["summaries"] if summary["label"] == "Issues started")
    assert opened_issues == {
        "label": "Issues started",
        "value": 6,
        "detail": "3.0/year · 3.0/month recently",
    }
    assert data["summaries"][0]["value"] == 10


def test_dashboard_derives_kind_personal_insights() -> None:
    """Lifecycle, return, conversation, and stewardship insights stay local."""
    issue_url = "https://github.com/octocat/example/issues/1"
    pr_url = "https://github.com/octocat/example/pull/2"
    events = [
        _ActivityEvent(
            category="opened_issues",
            occurred_at=datetime(2020, 1, 1, tzinfo=UTC),
            repository="octocat/example",
            title="A useful idea",
            url=issue_url,
            subject_type="issue",
            subject_author="octocat",
        ),
        _ActivityEvent(
            category="closed_issues",
            occurred_at=datetime(2020, 2, 1, tzinfo=UTC),
            repository="octocat/example",
            title="A useful idea",
            url=issue_url,
            subject_type="issue",
            subject_author="octocat",
        ),
        _ActivityEvent(
            category="opened_prs",
            occurred_at=datetime(2021, 3, 1, tzinfo=UTC),
            repository="octocat/example",
            title="Make it better",
            url=pr_url,
            subject_type="pull_request",
            subject_author="octocat",
        ),
        _ActivityEvent(
            category="merged_prs",
            occurred_at=datetime(2021, 3, 11, tzinfo=UTC),
            repository="octocat/example",
            title="Make it better",
            url=pr_url,
            subject_type="pull_request",
            subject_author="octocat",
        ),
        _ActivityEvent(
            category="comments",
            occurred_at=datetime(2023, 6, 1, tzinfo=UTC),
            repository="someone/community",
            title="Could this work?",
            url="https://github.com/someone/community/issues/8",
            subject_type="issue",
            subject_author="someone",
        ),
        _ActivityEvent(
            category="commits",
            occurred_at=datetime(2024, 7, 1, tzinfo=UTC),
            repository="octocat/example",
            count=5,
        ),
    ]
    aggregated = _aggregate_activity(
        events,
        now=datetime(2026, 8, 15, tzinfo=UTC),
    )

    data = _dashboard_data(
        aggregated=aggregated,
        events=events,
        commits=[],
        user="octocat",
        scope=["all repositories"],
    )

    assert data["hero"]["total"] == 10
    assert data["returns"]["count"] >= 3
    assert data["conversations"]["others"] == 1
    assert data["lifecycle"]["issues"]["closed"] == 1
    assert data["lifecycle"]["issues"]["median_days"] == 31
    assert data["lifecycle"]["prs"]["merged"] == 1
    assert data["repositories"]["count"] == 2
    assert data["repositories"]["stewardship"][0]["repository"] == "octocat/example"
    assert len(data["chapters"]) == 4
    assert len(data["firsts"]) == 6

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

"""Tests for commit-summary classification and insights."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from iseewhatyoudid._internal.activity import _CommitSummary
from iseewhatyoudid._internal.commit_analysis import (
    _analyze_commits,
    _classify_commit,
)


def _commit(
    headline: str,
    *,
    day: int = 1,
    year: int = 2026,
    repository: str = "octocat/example",
    source: str = "github",
    history_complete: bool = False,
    is_merge: bool | None = None,
) -> _CommitSummary:
    oid = f"{year}-{day}-{headline}"
    return _CommitSummary(
        oid=oid,
        headline=headline,
        committed_at=datetime(year, 1, day, tzinfo=UTC),
        repository=repository,
        url=f"https://github.com/{repository}/commit/{oid}",
        source=source,
        history_complete=history_complete,
        is_merge=is_merge,
    )


@pytest.mark.parametrize(
    ("headline", "category", "scope", "recognized"),
    [
        ("feat(parser)!: support aliases", "features", "parser", True),
        ("feature: add a dashboard", "features", None, True),
        ("fix: keep the cache safe", "fixes", None, True),
        ("docs(readme): explain usage", "documentation", "readme", True),
        ("tests: cover parsing", "tests", None, True),
        ("A perfectly useful summary", "other", None, False),
        ("custom(scope): useful work", "other", "scope", False),
    ],
)
def test_classify_commit(
    headline: str,
    category: str,
    scope: str | None,
    recognized: bool,
) -> None:
    """Conventional prefixes and forgiving aliases map to broad work kinds."""
    result = _classify_commit(_commit(headline))

    assert result.category == category
    assert result.scope == scope
    assert result.recognized is recognized


def test_analyze_commits_builds_all_dashboard_views() -> None:
    """One local pass derives the complete commit-analysis dashboard model."""
    commits = [_commit(f"feat(parser): add capability {day}", day=day) for day in range(1, 11)]
    commits.extend(
        [
            _commit("fix(cli): handle failure", day=11),
            _commit("docs: explain the parser", day=12),
            _commit("test(parser): cover capability", day=13),
            _commit(
                "chore: maintain release",
                day=1,
                year=2025,
                repository="someone/community",
            ),
            _commit(
                "security: validate input",
                day=2,
                year=2025,
                repository="someone/community",
            ),
            _commit("A summary without a prefix", day=14),
        ],
    )

    analysis = _analyze_commits(commits)

    assert analysis["available"] is True
    assert analysis["sample"]["commits"] == 16
    assert analysis["sample"]["repositories"] == 2
    assert analysis["sample"]["githubRepositories"] == 2
    assert analysis["sample"]["localRepositories"] == 0
    assert "Features" in analysis["kinds"]["labels"]
    assert analysis["composition"]["labels"] == ["2025", "2026"]
    assert analysis["cumulative"]["labels"]
    assert analysis["days"]
    assert analysis["matrix"]["repositories"][0] == "octocat/example"
    assert analysis["roles"][0]["primary"] == "Features"
    assert analysis["variety"]["data"] == [2, 5]
    assert analysis["milestones"][0]["value"] == 10
    assert len(analysis["firsts"]) == 7
    assert analysis["care"]["count"] == 4
    assert analysis["rhythm"]["datasets"]
    assert analysis["seasons"]
    assert len(analysis["gallery"]) == 16
    assert "capability" in analysis["topics"]["labels"]
    assert analysis["coverage"]["classified"] == 15
    assert analysis["insights"]


def test_default_merge_subjects_are_excluded_from_analysis() -> None:
    """Routine merge subjects do not affect categories, themes, or the gallery."""
    commits = [
        _commit("feat: useful work", day=1, is_merge=False),
        _commit(
            "Merge pull request #42 from contributor/topic",
            day=2,
            is_merge=True,
        ),
        _commit("Merge branch 'topic'", day=3),
        _commit("chore: integrate carefully", day=4, is_merge=True),
        _commit("Merge branch documentation", day=5, is_merge=False),
    ]

    analysis = _analyze_commits(commits)

    assert analysis["sample"]["commits"] == 3
    assert [item["headline"] for item in analysis["gallery"]] == [
        "Merge branch documentation",
        "chore: integrate carefully",
        "feat: useful work",
    ]
    assert "pull" not in analysis["topics"]["labels"]
    assert "request" not in analysis["topics"]["labels"]


def test_analyze_commits_discloses_local_and_shallow_sources() -> None:
    """The dashboard distinguishes complete, shallow, and API-backed histories."""
    commits = [
        _commit("feat: complete", source="local", history_complete=True),
        _commit(
            "fix: shallow",
            repository="octocat/shallow",
            source="local",
            history_complete=False,
        ),
        _commit("docs: sampled", repository="octocat/api"),
    ]

    sample = _analyze_commits(commits)["sample"]

    assert sample["localRepositories"] == 2
    assert sample["shallowRepositories"] == 1
    assert sample["githubRepositories"] == 1

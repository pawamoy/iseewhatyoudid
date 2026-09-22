"""Tests for GitHub CLI integration."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from iseewhatyoudid._internal.cache import _empty_cache, _save_cache
from iseewhatyoudid._internal.github_api import _GitHubClient
from iseewhatyoudid._internal.local_git import _LocalCommitResult, _LocalRemote


def _connection(
    nodes: list[dict[str, Any]],
    *,
    has_next: bool = False,
    cursor: str | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    return {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "totalCount": total if total is not None else len(nodes),
    }


def _public_issue(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "repository": {"nameWithOwner": "octocat/example", "isPrivate": False},
    }


def _public_pr(node_id: str) -> dict[str, Any]:
    return _public_issue(node_id)


def _public_comment(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "issue": {
            "repository": {
                "nameWithOwner": "octocat/example",
                "isPrivate": False,
            }
        },
        "pullRequest": None,
    }


def _private_issue(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "title": "PRIVATE_SENTINEL",
        "repository": {"nameWithOwner": "octocat/secret", "isPrivate": True},
    }


def _private_comment(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "issue": {
            "title": "PRIVATE_SENTINEL",
            "repository": {
                "nameWithOwner": "octocat/secret",
                "isPrivate": True,
            },
        },
        "pullRequest": None,
    }


def test_graphql_request_uses_gh_with_json_stdin(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """GraphQL text and variables are sent safely through standard input."""
    response = {"data": {"user": {"login": "octocat"}}}
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        assert set(kwargs) == {"capture_output", "check", "input", "text"}
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(response), stderr=""
        )

    monkeypatch.setattr("iseewhatyoudid._internal.github_api.subprocess.run", _run)
    caplog.set_level("INFO", logger="iseewhatyoudid._internal.github_api")

    assert (
        _GitHubClient()._request_graphql(
            "query User($login: String!) { user(login: $login) { login } }",
            variables={"login": "octocat"},
            operation="user lookup",
        )
        == response
    )
    assert len(calls) == 1
    assert calls[0][0] == ["gh", "api", "graphql", "--input", "-"]
    payload = json.loads(calls[0][1]["input"])
    assert payload["variables"] == {"login": "octocat"}
    assert "query User" in payload["query"]
    assert "Fetching user lookup from GitHub." in caplog.messages
    assert any(
        message.startswith("Fetched user lookup in") for message in caplog.messages
    )


def test_github_cli_failure_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub CLI failures are reported to the user."""
    result = subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="not logged in")
    monkeypatch.setattr(
        "iseewhatyoudid._internal.github_api.subprocess.run",
        lambda *args, **kwargs: result,
    )

    with pytest.raises(RuntimeError, match="not logged in"):
        _GitHubClient()._get_authenticated_user()


def test_partial_graphql_data_survives_gh_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing repositories do not discard usable aliases from a metadata batch."""
    response = {
        "data": {"r0": {"isPrivate": False}, "r1": None},
        "errors": [{"message": "Could not resolve one repository."}],
    }
    result = subprocess.CompletedProcess(
        ["gh"],
        1,
        stdout=json.dumps(response),
        stderr="gh: Could not resolve one repository.",
    )
    monkeypatch.setattr(
        "iseewhatyoudid._internal.github_api.subprocess.run",
        lambda *args, **kwargs: result,
    )

    assert (
        _GitHubClient()._request_graphql(
            "query Repositories { viewer { login } }",
            variables={},
            operation="repository metadata",
            allow_partial=True,
        )
        == response
    )


def test_empty_scope_includes_all_repositories() -> None:
    """No scope options means activity from every repository is included."""
    client = _GitHubClient()

    assert client._scope_labels(
        organizations=[],
        include_repositories=[],
        exclude_repositories=[],
    ) == ["all repositories"]
    assert client._is_in_scope(
        "pawamoy/iseewhatyoudid",
        organizations=[],
        include_repositories=[],
        exclude_repositories=[],
    )
    assert not client._is_in_scope(
        "pawamoy/iseewhatyoudid",
        organizations=[],
        include_repositories=[],
        exclude_repositories=["pawamoy/iseewhatyoudid"],
    )


def test_core_activity_combines_independent_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue, pull request, and comment pages share GraphQL requests."""
    responses = iter(
        [
            {
                "data": {
                    "user": {
                        "issues": _connection(
                            [_public_issue("issue-1"), _private_issue("private-issue")]
                        ),
                        "pullRequests": _connection(
                            [_public_pr("pr-1"), _private_issue("private-pr")]
                        ),
                        "issueComments": _connection(
                            [
                                _public_comment("comment-1"),
                                _private_comment("private-comment"),
                            ],
                            has_next=True,
                            cursor="comments-2",
                            total=101,
                        ),
                    },
                },
            },
            {
                "data": {
                    "user": {
                        "issueComments": _connection([_public_comment("comment-2")]),
                    },
                },
            },
        ],
    )
    calls: list[dict[str, Any]] = []

    def _request(
        query: str, *, variables: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        del query, operation
        calls.append(dict(variables))
        return next(responses)

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)
    cache = _empty_cache("octocat")

    issues, pull_requests, comments = client._collect_core_activity(
        user="octocat", cache=cache
    )

    assert set(issues) == {"issue-1"}
    assert set(pull_requests) == {"pr-1"}
    assert set(comments) == {"comment-1", "comment-2"}
    assert len(calls) == 2
    assert calls[0]["includeIssues"] is True
    assert calls[0]["includePrs"] is True
    assert calls[0]["includeComments"] is True
    assert calls[1]["includeIssues"] is False
    assert calls[1]["includePrs"] is False
    assert calls[1]["commentsCursor"] == "comments-2"
    assert all(cache["complete"].values())


def test_partial_checkpoint_does_not_end_history_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted first import continues beyond its cached newest page."""
    cached_comment = _public_comment("comment-1")
    cache = _empty_cache("octocat")
    cache["comments"]["comment-1"] = cached_comment
    cache["complete"]["issues"] = True
    cache["complete"]["pull_requests"] = True
    responses = iter(
        [
            {
                "data": {
                    "user": {
                        "issues": _connection([]),
                        "pullRequests": _connection([]),
                        "issueComments": _connection(
                            [cached_comment], has_next=True, cursor="older"
                        ),
                    },
                },
            },
            {
                "data": {
                    "user": {
                        "issueComments": _connection(
                            [_public_comment("comment-older")]
                        ),
                    },
                },
            },
        ],
    )
    calls = 0

    def _request(
        query: str, *, variables: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        nonlocal calls
        del query, variables, operation
        calls += 1
        return next(responses)

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)

    _, _, comments = client._collect_core_activity(user="octocat", cache=cache)

    assert calls == 2
    assert set(comments) == {"comment-1", "comment-older"}
    assert cache["complete"]["comments"] is True


def test_completed_history_stops_at_cached_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed history needs only its newest fully cached page."""
    cache = _empty_cache("octocat")
    cache["issues"]["issue-1"] = _public_issue("issue-1")
    cache["pull_requests"]["pr-1"] = _public_pr("pr-1")
    cache["comments"]["comment-1"] = _public_comment("comment-1")
    cache["complete"] = {key: True for key in cache["complete"]}
    calls = 0

    def _request(
        query: str, *, variables: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        nonlocal calls
        del query, variables, operation
        calls += 1
        return {
            "data": {
                "user": {
                    "issues": _connection(
                        [_public_issue("issue-1")],
                        has_next=True,
                        cursor="older-issues",
                    ),
                    "pullRequests": _connection(
                        [_public_pr("pr-1")], has_next=True, cursor="older-prs"
                    ),
                    "issueComments": _connection(
                        [_public_comment("comment-1")],
                        has_next=True,
                        cursor="older-comments",
                    ),
                },
            },
        }

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)

    client._collect_core_activity(user="octocat", cache=cache)

    assert calls == 1


def test_recent_cache_rebuilds_activity_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A quick rerun can rebuild the complete dashboard from disk."""
    repository = {"nameWithOwner": "octocat/example", "isPrivate": False}
    cache = _empty_cache("octocat")
    cache["updated_at"] = {
        key: datetime.now(timezone.utc).isoformat()
        for key in ("activity", "statuses", "commits", "commit_summaries")
    }
    cache["issues"]["issue-1"] = {
        "id": "issue-1",
        "createdAt": "2026-01-01T00:00:00Z",
        "closedAt": "2026-01-02T00:00:00Z",
        "repository": repository,
    }
    cache["comments"]["comment-1"] = {
        "id": "comment-1",
        "createdAt": "2026-01-03T00:00:00Z",
        "issue": {"repository": repository},
    }
    cache["issues"]["private-issue"] = {
        **_private_issue("private-issue"),
        "createdAt": "2026-01-01T00:00:00Z",
    }
    cache["pull_requests"]["private-pr"] = {
        **_private_issue("private-pr"),
        "createdAt": "2026-01-01T00:00:00Z",
    }
    cache["comments"]["private-comment"] = {
        **_private_comment("private-comment"),
        "createdAt": "2026-01-03T00:00:00Z",
    }
    cache["commit_years"]["2026"] = [
        {
            "occurredAt": "2026-01-04T00:00:00Z",
            "commitCount": 2,
            "repository": "octocat/example",
            "isPrivate": False,
        },
        {
            "occurredAt": "2026-01-04T00:00:00Z",
            "commitCount": 99,
            "repository": "octocat/secret",
            "isPrivate": True,
            "title": "PRIVATE_SENTINEL",
        },
    ]
    cache["commit_summaries"]["octocat/example"] = {}
    cache["commit_summaries"]["octocat/secret"] = {
        "private-commit": {
            "oid": "private-commit",
            "headline": "PRIVATE_SENTINEL",
            "committedAt": "2026-01-04T00:00:00Z",
            "url": "https://github.com/octocat/secret/commit/private",
            "repository": "octocat/secret",
            "isPrivate": True,
        }
    }
    _save_cache(cache, cache_dir=tmp_path)
    client = _GitHubClient(cache_dir=tmp_path)
    monkeypatch.setattr(
        client,
        "_request_graphql",
        lambda *args, **kwargs: pytest.fail("fresh cache should avoid GitHub requests"),
    )

    collected = client._collect_activity(
        user="octocat",
        organizations=[],
        include_repositories=[],
        exclude_repositories=[],
    )

    totals = {
        category: sum(
            event.count for event in collected.events if event.category == category
        )
        for category in {event.category for event in collected.events}
    }
    assert totals == {
        "opened_issues": 1,
        "closed_issues": 1,
        "comments": 1,
        "commits": 2,
    }
    assert "PRIVATE_SENTINEL" not in (tmp_path / "octocat.json").read_text(
        encoding="utf-8"
    )


def test_local_history_includes_repositories_absent_from_contribution_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A public local clone does not need to appear in GitHub contribution groups."""
    cache = _empty_cache("octocat")
    cache["updated_at"] = {
        key: datetime.now(timezone.utc).isoformat()
        for key in ("activity", "statuses", "commits", "commit_summaries")
    }
    cache["commit_years"]["2026"] = [
        {
            "occurredAt": "2026-01-01T00:00:00Z",
            "commitCount": 1,
            "repository": "octocat/example",
            "isPrivate": False,
        }
    ]
    cache["commit_summaries"]["octocat/example"] = {}
    _save_cache(cache, cache_dir=tmp_path)
    remote = _LocalRemote(
        path=tmp_path / "projects" / "example",
        remote="origin",
        repository="octocat/unlisted",
    )
    local_record = {
        "oid": "local-commit",
        "headline": "feat: read locally",
        "committedAt": "2026-01-01T00:00:00Z",
        "url": "https://github.com/octocat/unlisted/commit/local-commit",
        "repository": "octocat/unlisted",
        "isPrivate": False,
        "source": "local",
        "historyComplete": True,
    }

    monkeypatch.setattr(
        "iseewhatyoudid._internal.github_api._discover_local_remotes",
        lambda roots, known_repositories, progress_callback: [remote],
    )
    monkeypatch.setattr(
        "iseewhatyoudid._internal.github_api._collect_local_commit_summaries",
        lambda *args, **kwargs: _LocalCommitResult(
            records={"octocat/unlisted": {"local-commit": local_record}},
            repositories={"octocat/unlisted"},
        ),
    )
    client = _GitHubClient(cache_dir=tmp_path)
    monkeypatch.setattr(
        client,
        "_validate_public_repositories",
        lambda repositories, cache: {"octocat/unlisted": ("octocat/unlisted", "main")},
    )
    monkeypatch.setattr(
        client,
        "_collect_commit_summaries",
        lambda **kwargs: pytest.fail("local repositories must skip commit API history"),
    )

    collected = client._collect_activity(
        user="octocat",
        organizations=[],
        include_repositories=[],
        exclude_repositories=[],
        repositories_dirs=[tmp_path / "projects"],
        use_configured_identity=True,
    )

    assert len(collected.commits) == 1
    assert collected.commits[0].repository == "octocat/unlisted"
    assert collected.commits[0].source == "local"
    assert collected.commits[0].history_complete is True


def test_private_commit_groups_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private repository commit metadata never enters the year cache."""
    current_year = datetime.now(timezone.utc).year
    responses = iter(
        [
            {
                "data": {
                    "user": {
                        "contributionsCollection": {"contributionYears": [current_year]}
                    }
                }
            },
            {
                "data": {
                    "user": {
                        "contributionsCollection": {
                            "commitContributionsByRepository": [
                                {
                                    "repository": {
                                        "nameWithOwner": "octocat/example",
                                        "isPrivate": False,
                                    },
                                    "early": {
                                        "totalCount": 1,
                                        "nodes": [
                                            {
                                                "occurredAt": f"{current_year}-01-01T00:00:00Z",
                                                "commitCount": 2,
                                            }
                                        ],
                                    },
                                    "recent": {"nodes": []},
                                },
                                {
                                    "repository": {
                                        "nameWithOwner": "octocat/secret",
                                        "isPrivate": True,
                                    },
                                    "early": {
                                        "totalCount": 1,
                                        "nodes": [
                                            {
                                                "occurredAt": f"{current_year}-01-02T00:00:00Z",
                                                "commitCount": 99,
                                            }
                                        ],
                                    },
                                    "recent": {"nodes": []},
                                },
                            ]
                        }
                    }
                }
            },
        ]
    )
    client = _GitHubClient()
    monkeypatch.setattr(
        client,
        "_request_graphql",
        lambda *args, **kwargs: next(responses),
    )

    years = client._collect_commit_years(user="octocat", cached_years={})

    assert years[str(current_year)] == [
        {
            "occurredAt": f"{current_year}-01-01T00:00:00Z",
            "commitCount": 2,
            "repository": "octocat/example",
            "isPrivate": False,
        }
    ]


def test_commit_summaries_are_bounded_batched_and_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial enrichment takes one page per public repository and drops private data."""
    cache = _empty_cache("octocat")
    cache["user_id"] = "user-node-id"
    calls: list[tuple[str, dict[str, Any]]] = []

    def _request(
        query: str,
        *,
        variables: dict[str, Any],
        operation: str,
        allow_partial: bool,
    ) -> dict[str, Any]:
        del operation
        assert allow_partial is True
        calls.append((query, variables))
        return {
            "data": {
                "r0": {
                    "nameWithOwner": "octocat/example",
                    "isPrivate": False,
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "nodes": [
                                    {
                                        "oid": "commit-1",
                                        "messageHeadline": "feat: add a thing",
                                        "committedDate": "2026-01-01T00:00:00Z",
                                        "url": "https://github.com/octocat/example/commit/commit-1",
                                    }
                                ],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "older-public-commits",
                                },
                            }
                        }
                    },
                },
                "r1": {
                    "nameWithOwner": "octocat/secret",
                    "isPrivate": True,
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "nodes": [
                                    {
                                        "oid": "private-commit",
                                        "messageHeadline": "PRIVATE_SENTINEL",
                                        "committedDate": "2026-01-01T00:00:00Z",
                                        "url": "https://github.com/octocat/secret/commit/private",
                                    }
                                ],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                            }
                        }
                    },
                },
            }
        }

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)
    monkeypatch.setattr(client, "_checkpoint_cache", lambda cache: None)

    summaries = client._collect_commit_summaries(
        user="octocat",
        repositories=["octocat/example", "octocat/secret"],
        cache=cache,
    )

    assert len(calls) == 1
    assert "history(first: 100" in calls[0][0]
    assert calls[0][1]["author"] == "user-node-id"
    assert set(summaries) == {"octocat/example"}
    assert set(summaries["octocat/example"]) == {"commit-1"}
    assert "octocat/secret" not in cache["commit_summaries"]


def test_local_repository_metadata_requires_public_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only confirmed-public clones receive a default branch or retain cache data."""
    cache = _empty_cache("octocat")
    cache["local_repositories"]["octocat/example"] = {"head": "public"}
    cache["commit_summaries"]["octocat/example"] = {"public": {}}
    cache["local_repositories"]["OctoCat/Secret"] = {"head": "private"}
    cache["commit_summaries"]["OctoCat/Secret"] = {"private": {}}

    def _request(
        query: str,
        *,
        variables: dict[str, Any],
        operation: str,
        allow_partial: bool,
    ) -> dict[str, Any]:
        del operation
        assert "defaultBranchRef" in query
        assert variables["owner0"] == "octocat"
        assert allow_partial is True
        return {
            "data": {
                "r0": {
                    "nameWithOwner": "OctoCat/Example",
                    "isPrivate": False,
                    "defaultBranchRef": {"name": "main"},
                },
                "r1": {
                    "isPrivate": True,
                    "defaultBranchRef": {"name": "main"},
                },
            }
        }

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)
    monkeypatch.setattr(client, "_checkpoint_cache", lambda cache: None)

    branches = client._validate_public_repositories(
        ["octocat/example", "octocat/secret"], cache=cache
    )

    assert branches == {"octocat/example": ("OctoCat/Example", "main")}
    assert "OctoCat/Example" in cache["repository_metadata"]
    assert cache["local_repositories"] == {"OctoCat/Example": {"head": "public"}}
    assert cache["commit_summaries"] == {"OctoCat/Example": {"public": {}}}


def test_commit_summary_refresh_stops_on_known_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incremental page merges new commits and stops at cached history."""
    cache = _empty_cache("octocat")
    cache["user_id"] = "user-node-id"
    cache["commit_summaries"]["octocat/example"] = {
        "known": {
            "oid": "known",
            "headline": "fix: known work",
            "committedAt": "2025-01-01T00:00:00Z",
            "url": "https://github.com/octocat/example/commit/known",
            "repository": "octocat/example",
            "isPrivate": False,
        }
    }
    calls = 0

    def _request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "data": {
                "r0": {
                    "nameWithOwner": "octocat/example",
                    "isPrivate": False,
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "nodes": [
                                    {
                                        "oid": "new",
                                        "messageHeadline": "docs: new work",
                                        "committedDate": "2026-01-01T00:00:00Z",
                                        "url": "https://github.com/octocat/example/commit/new",
                                    },
                                    {
                                        "oid": "known",
                                        "messageHeadline": "fix: known work",
                                        "committedDate": "2025-01-01T00:00:00Z",
                                        "url": "https://github.com/octocat/example/commit/known",
                                    },
                                ],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "older",
                                },
                            }
                        }
                    },
                }
            }
        }

    client = _GitHubClient()
    monkeypatch.setattr(client, "_request_graphql", _request)
    monkeypatch.setattr(client, "_checkpoint_cache", lambda cache: None)

    summaries = client._collect_commit_summaries(
        user="octocat",
        repositories=["octocat/example"],
        cache=cache,
    )

    assert calls == 1
    assert set(summaries["octocat/example"]) == {"known", "new"}

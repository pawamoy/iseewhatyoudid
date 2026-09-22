"""Tests for reading commit summaries from local public clones."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iseewhatyoudid._internal.cache import _empty_cache
from iseewhatyoudid._internal.local_git import (
    _MAX_COMMITS_PER_REPOSITORY,
    _collect_local_commit_summaries,
    _discover_local_remotes,
    _limit_records,
    _normalize_github_remote,
)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _commit(repository: Path, headline: str, sequence: int) -> None:
    tracked = repository / "history.txt"
    with tracked.open("a", encoding="utf-8") as stream:
        stream.write(f"{headline}\n")
    _git(repository, "add", "history.txt")
    environment = dict(os.environ)
    environment["GIT_AUTHOR_DATE"] = f"2026-01-{sequence:02d}T12:00:00Z"
    environment["GIT_COMMITTER_DATE"] = environment["GIT_AUTHOR_DATE"]
    result = subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", headline],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "projects" / "example"
    repository.mkdir(parents=True)
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Octo Cat")
    _git(repository, "config", "user.email", "octocat@example.com")
    _git(repository, "config", "commit.gpgsign", "false")
    _git(repository, "remote", "add", "origin", "git@github.com:octocat/example.git")
    return repository


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:octocat/example.git",
        "Git@GitHub.com:octocat/example.git",
        "https://github.com/octocat/example.git",
        "ssh://git@github.com/octocat/example.git",
        "github.com/octocat/example",
    ],
)
def test_normalize_github_remote(url: str) -> None:
    """Common GitHub remote forms resolve to the same repository name."""
    assert _normalize_github_remote(url) == "octocat/example"


def test_discovery_returns_known_and_unknown_github_repositories(
    tmp_path: Path,
) -> None:
    """Contribution data canonicalizes known remotes without excluding the others."""
    repository = _repository(tmp_path)
    _git(
        repository,
        "remote",
        "add",
        "contributor",
        "git@github.com:someone/example.git",
    )

    known = _discover_local_remotes(
        [tmp_path / "projects"], known_repositories=["octocat/example"]
    )
    assert [(remote.path, remote.remote) for remote in known] == [
        (repository, "origin")
    ]
    unknown = _discover_local_remotes(
        [tmp_path / "projects"], known_repositories=["octocat/elsewhere"]
    )
    assert unknown[0].repository == "octocat/example"


def test_discovery_descends_when_root_is_a_git_repository(tmp_path: Path) -> None:
    """A Git-backed repository container does not hide clones nested below it."""
    repository = _repository(tmp_path)
    container = tmp_path / "projects"
    _git(container, "init")

    discovered = _discover_local_remotes([container])

    assert [remote.path for remote in discovered] == [repository]


def test_local_commits_are_cached_and_updated_incrementally(tmp_path: Path) -> None:
    """Local default-branch history is cached by head and extended after new commits."""
    repository = _repository(tmp_path)
    _commit(repository, "feat: begin", 1)
    _commit(repository, "fix: follow through", 2)
    remote = _discover_local_remotes(
        [tmp_path / "projects"], known_repositories=["octocat/example"]
    )
    cache = _empty_cache("octocat")

    first = _collect_local_commit_summaries(
        remote,
        default_branches={"octocat/example": "main"},
        login="octocat",
        explicit_emails=["octocat@example.com"],
        use_configured_identity=False,
        cache=cache,
    )

    assert first.repositories == {"octocat/example"}
    assert len(first.records["octocat/example"]) == 2
    assert all(
        record["source"] == "local" and record["historyComplete"] is True
        for record in first.records["octocat/example"].values()
    )
    assert str(tmp_path) not in json.dumps(cache)

    _commit(repository, "docs: remember the journey", 3)
    second = _collect_local_commit_summaries(
        remote,
        default_branches={"octocat/example": "main"},
        login="octocat",
        explicit_emails=["octocat@example.com"],
        use_configured_identity=False,
        cache=cache,
    )

    assert len(second.records["octocat/example"]) == 3


def test_local_author_identity_is_explicit(tmp_path: Path) -> None:
    """A selected third-party user does not inherit unrelated local Git identities."""
    repository = _repository(tmp_path)
    _commit(repository, "feat: local identity", 1)
    remote = _discover_local_remotes(
        [tmp_path / "projects"], known_repositories=["octocat/example"]
    )

    result = _collect_local_commit_summaries(
        remote,
        default_branches={"octocat/example": "main"},
        login="someone-else",
        explicit_emails=[],
        use_configured_identity=False,
        cache=_empty_cache("someone-else"),
    )

    assert result.repositories == {"octocat/example"}
    assert result.records["octocat/example"] == {}


def test_local_cache_keeps_newest_two_thousand_commits() -> None:
    """Oversized local histories retain only the newest configured allowance."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    records = {
        str(index): {
            "committedAt": (start + timedelta(minutes=index)).isoformat(),
        }
        for index in range(_MAX_COMMITS_PER_REPOSITORY + 5)
    }

    limited = _limit_records(records)

    assert len(limited) == _MAX_COMMITS_PER_REPOSITORY
    assert "0" not in limited
    assert "4" not in limited
    assert "5" in limited
    assert str(_MAX_COMMITS_PER_REPOSITORY + 4) in limited

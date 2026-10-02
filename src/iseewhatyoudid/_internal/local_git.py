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

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)
_ProgressCallback = Callable[[str, int, int | None], None]
_MAX_COMMITS_PER_REPOSITORY = 2_000
_REPOSITORY_NAME_PARTS = 2
_LOG_FIELD_COUNT = 6
_IGNORED_DIRECTORIES = {
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class _LocalRemote:
    path: Path
    remote: str
    repository: str


@dataclass
class _LocalCommitResult:
    records: dict[str, dict[str, dict[str, Any]]]
    repositories: set[str]


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _run_git(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(path), *arguments],  # noqa: S607
            capture_output=True,
            check=False,
            encoding="utf8",
            env=_git_environment(),
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "Git is required when using `--repos-dir`. Install Git or omit the option.",
        ) from error
    except OSError as error:
        raise RuntimeError(
            f"Could not inspect local Git repository: {error}",
        ) from error


def _normalize_github_remote(url: str) -> str | None:
    value = url.strip()
    scp_remote = re.fullmatch(r"(?:[^@]+@)?github\.com:(.+)", value, flags=re.IGNORECASE)
    if scp_remote:
        path = scp_remote.group(1)
    elif "://" in value:
        parsed = urlparse(value)
        if (parsed.hostname or "").lower() != "github.com":
            return None
        path = parsed.path.lstrip("/")
    elif value.lower().startswith("github.com/"):
        path = value.split("/", 1)[1]
    else:
        return None
    path = path.removesuffix(".git").strip("/")
    parts = path.split("/")
    if len(parts) != _REPOSITORY_NAME_PARTS or not all(parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def _repository_paths(roots: list[Path]) -> list[Path]:
    repositories = []
    seen: set[Path] = set()
    for root in roots:
        expanded = root.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            raise RuntimeError(f"Local repository directory does not exist: {root}")
        root_path = expanded.resolve()
        for directory, names, files in os.walk(expanded, followlinks=False):
            current = Path(directory)
            if ".git" in names or ".git" in files:
                resolved = current.resolve()
                if resolved not in seen:
                    repositories.append(current)
                    seen.add(resolved)
                if resolved != root_path:
                    names.clear()
                    continue
                if ".git" in names:
                    names.remove(".git")
            names[:] = [
                name for name in names if name not in _IGNORED_DIRECTORIES and not (current / name).is_symlink()
            ]
    return repositories


def _discover_local_remotes(
    roots: list[Path],
    *,
    known_repositories: list[str] | None = None,
    progress_callback: _ProgressCallback | None = None,
) -> list[_LocalRemote]:
    canonical = {repository.lower(): repository for repository in known_repositories or []}
    matches = []
    seen: set[tuple[Path, str, str]] = set()
    paths = _repository_paths(roots)
    operation = f"local remotes from {len(paths)} repositories"
    if progress_callback:
        progress_callback(operation, 0, len(paths))
    for index, path in enumerate(paths, start=1):
        result = _run_git(path, "config", "--get-regexp", r"^remote\..*\.url$")
        if result.returncode not in (0, 1):
            _logger.info("Could not inspect remotes for one local repository.")
            if progress_callback:
                progress_callback(operation, index, len(paths))
            continue
        for line in result.stdout.splitlines():
            try:
                key, url = line.split(maxsplit=1)
            except ValueError:
                continue
            match = re.fullmatch(r"remote\.([^.]+)\.url", key)
            normalized = _normalize_github_remote(url)
            if not match or match.group(1) != "origin" or not normalized:
                continue
            repository = canonical.get(normalized.lower(), normalized)
            item_key = (path.resolve(), match.group(1), repository)
            if item_key not in seen:
                matches.append(
                    _LocalRemote(
                        path=path,
                        remote=match.group(1),
                        repository=repository,
                    ),
                )
                seen.add(item_key)
        if progress_callback:
            progress_callback(operation, index, len(paths))
    return matches


def _ref_exists(path: Path, reference: str) -> bool:
    result = _run_git(
        path,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{reference}^{{commit}}",
    )
    return result.returncode == 0


def _default_branch_ref(
    remote: _LocalRemote,
    *,
    github_default_branch: str | None,
) -> str | None:
    candidates = []
    if github_default_branch:
        candidates.extend(
            (
                f"refs/remotes/{remote.remote}/{github_default_branch}",
                f"refs/heads/{github_default_branch}",
            ),
        )
    symbolic = _run_git(
        remote.path,
        "symbolic-ref",
        "--quiet",
        f"refs/remotes/{remote.remote}/HEAD",
    )
    if symbolic.returncode == 0 and symbolic.stdout.strip():
        candidates.append(symbolic.stdout.strip())
    candidates.extend(
        (
            f"refs/remotes/{remote.remote}/main",
            f"refs/remotes/{remote.remote}/master",
            "refs/heads/main",
            "refs/heads/master",
        ),
    )
    for candidate in dict.fromkeys(candidates):
        if _ref_exists(remote.path, candidate):
            return candidate
    return None


def _configured_emails(path: Path) -> set[str]:
    result = _run_git(path, "config", "--get-all", "user.email")
    if result.returncode not in (0, 1):
        return set()
    return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}


def _shallow_fingerprint(path: Path) -> str | None:
    result = _run_git(path, "rev-parse", "--git-path", "shallow")
    if result.returncode or not result.stdout.strip():
        return None
    shallow_path = Path(result.stdout.strip())
    if not shallow_path.is_absolute():
        shallow_path = path / shallow_path
    try:
        return hashlib.sha256(shallow_path.read_bytes()).hexdigest()
    except OSError:
        return None


def _email_matches(email: str, *, login: str, identities: set[str]) -> bool:
    normalized = email.strip().lower()
    if normalized in identities:
        return True
    escaped = re.escape(login.lower())
    return bool(
        re.fullmatch(
            rf"(?:\d+\+)?{escaped}@users\.noreply\.github\.com",
            normalized,
        ),
    )


def _identity_fingerprint(login: str, identities: set[str]) -> str:
    source = "\0".join((login.lower(), *sorted(identities)))
    return hashlib.sha256(source.encode()).hexdigest()


def _parse_log(
    output: str,
    *,
    repository: str,
    login: str,
    identities: set[str],
    shallow: bool,
) -> dict[str, dict[str, Any]]:
    records = {}
    for raw_record in output.split("\x1e"):
        fields = raw_record.strip("\r\n").split("\x1f", _LOG_FIELD_COUNT - 1)
        if len(fields) != _LOG_FIELD_COUNT:
            continue
        (
            oid,
            committed_at,
            original_email,
            canonical_email,
            parents,
            headline,
        ) = fields
        if (
            not oid
            or not headline
            or not (
                _email_matches(original_email, login=login, identities=identities)
                or _email_matches(canonical_email, login=login, identities=identities)
            )
        ):
            continue
        records[oid] = {
            "oid": oid,
            "headline": headline,
            "committedAt": committed_at,
            "url": f"https://github.com/{repository}/commit/{oid}",
            "repository": repository,
            "isPrivate": False,
            "source": "local",
            "historyComplete": not shallow,
            "isMerge": len(parents.split()) > 1,
        }
    return records


def _record_timestamp(record: dict[str, Any]) -> float:
    value = record.get("committedAt")
    if not isinstance(value, str):
        return float("-inf")
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return float("-inf")


def _limit_records(
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    newest = sorted(
        records.items(),
        key=lambda item: (_record_timestamp(item[1]), item[0]),
        reverse=True,
    )[:_MAX_COMMITS_PER_REPOSITORY]
    return dict(newest)


def _read_matching_log(
    path: Path,
    revision: str,
    *,
    repository: str,
    login: str,
    identities: set[str],
    shallow: bool,
) -> dict[str, dict[str, Any]] | None:
    try:
        process = subprocess.Popen(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(path),
                "log",
                revision,
                "--use-mailmap",
                "--no-show-signature",
                "--format=%H%x1f%cI%x1f%ae%x1f%aE%x1f%P%x1f%s",
            ],
            encoding="utf8",
            env=_git_environment(),
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "Git is required when using `--repos-dir`. Install Git or omit the option.",
        ) from error
    except OSError as error:
        raise RuntimeError(
            f"Could not inspect local Git repository: {error}",
        ) from error

    records: dict[str, dict[str, Any]] = {}
    reached_limit = False
    if process.stdout is not None:
        for line in process.stdout:
            records.update(
                _parse_log(
                    line,
                    repository=repository,
                    login=login,
                    identities=identities,
                    shallow=shallow,
                ),
            )
            if len(records) >= _MAX_COMMITS_PER_REPOSITORY:
                reached_limit = True
                process.terminate()
                break
        process.stdout.close()
    return_code = process.wait()
    if return_code and not reached_limit:
        return None
    return records


def _collect_local_commit_summaries(
    remotes: list[_LocalRemote],
    *,
    default_branches: dict[str, str | None],
    login: str,
    explicit_emails: list[str],
    use_configured_identity: bool,
    cache: dict[str, Any],
    progress_callback: _ProgressCallback | None = None,
) -> _LocalCommitResult:
    records: dict[str, dict[str, dict[str, Any]]] = {}
    repositories: set[str] = set()
    by_repository: dict[str, list[_LocalRemote]] = {}
    for remote in remotes:
        by_repository.setdefault(remote.repository, []).append(remote)
    operation = f"local commit history from {len(by_repository)} repositories"
    for index, (repository, candidates) in enumerate(by_repository.items(), start=1):
        if progress_callback:
            progress_callback(operation, index - 1, len(by_repository))
        for remote in candidates:
            reference = _default_branch_ref(
                remote,
                github_default_branch=default_branches.get(repository),
            )
            if not reference:
                continue
            head_result = _run_git(remote.path, "rev-parse", reference)
            if head_result.returncode or not head_result.stdout.strip():
                continue
            head = head_result.stdout.strip()
            shallow_result = _run_git(
                remote.path,
                "rev-parse",
                "--is-shallow-repository",
            )
            shallow = shallow_result.stdout.strip() == "true"
            shallow_fingerprint = _shallow_fingerprint(remote.path) if shallow else None
            identities = {email.strip().lower() for email in explicit_emails if email.strip()}
            if use_configured_identity:
                identities.update(_configured_emails(remote.path))
            identity = _identity_fingerprint(login, identities)
            state = cache["local_repositories"].get(repository)
            cached_records = {
                oid: record
                for oid, record in cache["commit_summaries"].get(repository, {}).items()
                if isinstance(record, dict) and record.get("source") == "local"
            }
            if (
                isinstance(state, dict)
                and state.get("head") == head
                and state.get("ref") == reference
                and state.get("identity") == identity
                and state.get("shallow") is shallow
                and (
                    not shallow
                    or (shallow_fingerprint is not None and state.get("shallowFingerprint") == shallow_fingerprint)
                )
            ):
                cached_records = _limit_records(cached_records)
                cache["commit_summaries"][repository] = {
                    oid: record
                    for oid, record in cache["commit_summaries"].get(repository, {}).items()
                    if isinstance(record, dict) and record.get("source") != "local"
                }
                cache["commit_summaries"][repository].update(cached_records)
                records[repository] = cached_records
                repositories.add(repository)
                break

            revision = reference
            incremental = False
            if (
                isinstance(state, dict)
                and isinstance(state.get("head"), str)
                and state.get("identity") == identity
                and not shallow
            ):
                old_head = state["head"]
                ancestor = _run_git(
                    remote.path,
                    "merge-base",
                    "--is-ancestor",
                    old_head,
                    head,
                )
                if ancestor.returncode == 0:
                    revision = f"{old_head}..{reference}"
                    incremental = True

            parsed = _read_matching_log(
                remote.path,
                revision,
                repository=repository,
                login=login,
                identities=identities,
                shallow=shallow,
            )
            if parsed is None:
                continue
            repository_records = cached_records if incremental else {}
            repository_records.update(parsed)
            repository_records = _limit_records(repository_records)
            cache["commit_summaries"].setdefault(repository, {})
            cache["commit_summaries"][repository] = {
                oid: record
                for oid, record in cache["commit_summaries"][repository].items()
                if isinstance(record, dict) and record.get("source") != "local"
            }
            cache["commit_summaries"][repository].update(repository_records)
            cache["local_repositories"][repository] = {
                "head": head,
                "ref": reference,
                "identity": identity,
                "shallow": shallow,
                "shallowFingerprint": shallow_fingerprint,
            }
            records[repository] = repository_records
            repositories.add(repository)
            break
        if progress_callback:
            progress_callback(operation, index, len(by_repository))
    return _LocalCommitResult(records=records, repositories=repositories)

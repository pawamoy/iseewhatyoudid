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

import json
import logging
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING, Any

from iseewhatyoudid._internal.activity import (
    _ActivityEvent,
    _CollectedActivity,
    _CommitSummary,
)
from iseewhatyoudid._internal.cache import _load_cache, _save_cache
from iseewhatyoudid._internal.local_git import (
    _collect_local_commit_summaries,
    _discover_local_remotes,
    _LocalRemote,
)

if TYPE_CHECKING:
    from pathlib import Path


_logger = logging.getLogger(__name__)
_ProgressCallback = Callable[[str, int, int | None], None]
_CACHE_FRESHNESS = timedelta(minutes=15)
_MAX_COMMIT_REPOSITORIES = 20
_COMMIT_REPOSITORY_BATCH_SIZE = 10
_COMMIT_PAGE_SIZE = 100
_MAX_INCREMENTAL_COMMIT_PAGES = 3
_REPOSITORY_METADATA_BATCH_SIZE = 50


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _is_public_activity_node(connection: str, node: dict[str, Any]) -> bool:
    if connection == "issueComments":
        pull_request = node.get("pullRequest")
        issue = node.get("issue")
        subject = pull_request if isinstance(pull_request, dict) else issue
        repository = subject.get("repository") if isinstance(subject, dict) else None
    else:
        repository = node.get("repository")
    return isinstance(repository, dict) and repository.get("isPrivate") is False


def _take_repository_cache(cache: dict[str, Any], repository: str) -> dict[str, Any]:
    normalized = repository.lower()
    entries = {}
    for cache_key in (
        "repository_metadata",
        "local_repositories",
        "commit_summaries",
    ):
        mapping = cache[cache_key]
        for cached_repository in list(mapping):
            if cached_repository.lower() == normalized:
                entries[cache_key] = mapping.pop(cached_repository)
    return entries


def _purge_repository_cache(cache: dict[str, Any], repository: str) -> None:
    _take_repository_cache(cache, repository)


class _GitHubClient:
    def __init__(
        self,
        *,
        progress_callback: _ProgressCallback | None = None,
        cache_dir: Path | None = None,
        force_refresh: bool = False,
    ) -> None:
        self._progress_callback = progress_callback
        self._cache_dir = cache_dir
        self._force_refresh = force_refresh

    def _cache_is_fresh(self, cache: dict[str, Any], key: str) -> bool:
        if self._force_refresh:
            return False
        value = cache["updated_at"].get(key)
        if not isinstance(value, str):
            return False
        try:
            updated_at = _parse_datetime(value)
            age = datetime.now(UTC) - updated_at
        except (TypeError, ValueError):
            return False
        return age <= _CACHE_FRESHNESS

    def _mark_cache_updated(self, cache: dict[str, Any], key: str) -> None:
        cache["updated_at"][key] = datetime.now(UTC).isoformat()

    def _request_graphql(
        self,
        query: str,
        *,
        variables: dict[str, Any],
        operation: str,
        allow_partial: bool = False,
    ) -> dict[str, Any]:
        command = ["gh", "api", "graphql", "--input", "-"]
        payload = json.dumps({"query": query, "variables": variables})
        _logger.info("Fetching %s from GitHub.", operation)
        started = monotonic()
        try:
            result = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                check=False,
                encoding="utf8",
                input=payload,
                text=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "GitHub CLI (`gh`) is required. Install it and run `gh auth login`.",
            ) from error
        except OSError as error:
            raise RuntimeError(f"Could not run GitHub CLI: {error}") from error

        try:
            decoded: object = json.loads(result.stdout)
        except json.JSONDecodeError:
            decoded = None

        partial_response = allow_partial and isinstance(decoded, dict) and isinstance(decoded.get("data"), dict)
        if result.returncode and not partial_response:
            details = result.stderr.strip() or result.stdout.strip() or "no error details provided"
            raise RuntimeError(f"GitHub CLI GraphQL request failed: {details}")
        if not isinstance(decoded, dict):
            # Report malformed GitHub responses through the CLI's runtime error handler.
            raise RuntimeError(  # noqa: TRY004
                "GitHub CLI returned invalid JSON or a malformed response.",
            )
        errors = decoded.get("errors")
        if isinstance(errors, list) and errors:
            messages = [str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors]
            if not allow_partial:
                raise RuntimeError("GitHub GraphQL error: " + "; ".join(messages))
            _logger.warning(
                "GitHub returned partial data for %s: %s",
                operation,
                "; ".join(messages),
            )
        _logger.info("Fetched %s in %.1f seconds.", operation, monotonic() - started)
        return decoded

    def _report_progress(
        self,
        operation: str,
        *,
        completed: int,
        total: int | None,
    ) -> None:
        if self._progress_callback:
            self._progress_callback(operation, completed, total)

    def _checkpoint_cache(self, cache: dict[str, Any]) -> None:
        try:
            _save_cache(cache, cache_dir=self._cache_dir)
        except OSError as error:
            _logger.warning("Could not update activity cache: %s", error)

    def _strip_private_cache(self, cache: dict[str, Any]) -> None:
        for cache_key, connection in (
            ("issues", "issues"),
            ("pull_requests", "pullRequests"),
            ("comments", "issueComments"),
        ):
            cache[cache_key] = {
                key: node
                for key, node in cache[cache_key].items()
                if isinstance(node, dict) and _is_public_activity_node(connection, node)
            }
        cache["commit_years"] = {
            year: [record for record in records if isinstance(record, dict) and record.get("isPrivate") is False]
            for year, records in cache["commit_years"].items()
            if isinstance(records, list)
        }
        cache["commit_summaries"] = {
            repository: {
                oid: record
                for oid, record in records.items()
                if isinstance(record, dict)
                and record.get("isPrivate") is False
                and record.get("repository") == repository
            }
            for repository, records in cache["commit_summaries"].items()
            if isinstance(records, dict)
        }
        cache["repository_metadata"] = {
            repository: metadata
            for repository, metadata in cache["repository_metadata"].items()
            if isinstance(metadata, dict) and metadata.get("isPrivate") is False
        }
        cache["local_repositories"] = {
            repository: state
            for repository, state in cache["local_repositories"].items()
            if repository in cache["repository_metadata"] and isinstance(state, dict)
        }

    def _collect_core_activity(
        self,
        *,
        user: str,
        cache: dict[str, Any],
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        query = """
query UserActivity(
  $login: String!
  $issuesCursor: String
  $prsCursor: String
  $commentsCursor: String
  $includeIssues: Boolean!
  $includePrs: Boolean!
  $includeComments: Boolean!
) {
  user(login: $login) {
    id
    issues(first: 100, after: $issuesCursor, orderBy: {field: CREATED_AT, direction: DESC})
      @include(if: $includeIssues) {
      totalCount pageInfo { hasNextPage endCursor }
      nodes {
        id number title url createdAt closedAt
        author { login }
        repository { nameWithOwner isPrivate }
      }
    }
    pullRequests(first: 100, after: $prsCursor, orderBy: {field: CREATED_AT, direction: DESC})
      @include(if: $includePrs) {
      totalCount pageInfo { hasNextPage endCursor }
      nodes {
        id number title url createdAt closedAt mergedAt merged state
        author { login }
        repository { nameWithOwner isPrivate }
      }
    }
    issueComments(first: 100, after: $commentsCursor, orderBy: {field: UPDATED_AT, direction: DESC})
      @include(if: $includeComments) {
      totalCount pageInfo { hasNextPage endCursor }
      nodes {
        id createdAt updatedAt
        issue {
          id number title url author { login }
          repository { nameWithOwner isPrivate }
        }
        pullRequest {
          id number title url author { login }
          repository { nameWithOwner isPrivate }
        }
      }
    }
  }
}
"""
        items = {
            "issues": {
                key: node
                for key, node in cache["issues"].items()
                if isinstance(node, dict) and _is_public_activity_node("issues", node)
            },
            "pullRequests": {
                key: node
                for key, node in cache["pull_requests"].items()
                if isinstance(node, dict) and _is_public_activity_node("pullRequests", node)
            },
            "issueComments": {
                key: node
                for key, node in cache["comments"].items()
                if isinstance(node, dict) and _is_public_activity_node("issueComments", node)
            },
        }
        cache_keys = {
            "issues": "issues",
            "pullRequests": "pull_requests",
            "issueComments": "comments",
        }
        labels = {
            "issues": f"issues for {user}",
            "pullRequests": f"pull requests for {user}",
            "issueComments": f"comments for {user}",
        }
        variable_names = {
            "issues": ("issuesCursor", "includeIssues"),
            "pullRequests": ("prsCursor", "includePrs"),
            "issueComments": ("commentsCursor", "includeComments"),
        }
        active = dict.fromkeys(items, True)
        cursors: dict[str, str | None] = dict.fromkeys(items)
        pages = dict.fromkeys(items, 0)
        totals: dict[str, int | None] = dict.fromkeys(items)
        history_complete = {
            name: bool(cache["complete"].get(cache_key, False)) for name, cache_key in cache_keys.items()
        }
        request_count = 0

        while any(active.values()):
            variables: dict[str, Any] = {"login": user}
            for name, (cursor_variable, include_variable) in variable_names.items():
                variables[cursor_variable] = cursors[name]
                variables[include_variable] = active[name]
                if active[name]:
                    self._report_progress(
                        labels[name],
                        completed=pages[name],
                        total=totals[name],
                    )

            response = self._request_graphql(
                query,
                variables=variables,
                operation=f"activity page {request_count + 1} for {user}",
            )
            request_count += 1
            data = response.get("data")
            account = data.get("user") if isinstance(data, dict) else None
            if not isinstance(account, dict):
                # A missing GitHub user is a request failure, not a caller type error.
                raise RuntimeError(  # noqa: TRY004
                    f"GitHub user {user!r} was not found or is unavailable.",
                )
            if isinstance(account.get("id"), str):
                cache["user_id"] = account["id"]

            for name, connection_items in items.items():
                if not active[name]:
                    continue
                connection = account.get(name)
                if not isinstance(connection, dict):
                    active[name] = False
                    continue
                if isinstance(connection.get("totalCount"), int):
                    totals[name] = max(1, ceil(connection["totalCount"] / 100))
                nodes = connection.get("nodes")
                page_nodes = [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []
                public_nodes = [node for node in page_nodes if _is_public_activity_node(name, node)]
                private_count = len(page_nodes) - len(public_nodes)
                if private_count:
                    _logger.info(
                        "Discarded %s private or unavailable %s record(s).",
                        private_count,
                        labels[name],
                    )
                new_items = 0
                for node in public_nodes:
                    node_id = node.get("id")
                    if not isinstance(node_id, str):
                        continue
                    if node_id not in connection_items:
                        new_items += 1
                    connection_items[node_id] = node
                pages[name] += 1
                self._report_progress(
                    labels[name],
                    completed=pages[name],
                    total=totals[name],
                )

                page_info = connection.get("pageInfo")
                has_next = isinstance(page_info, dict) and bool(
                    page_info.get("hasNextPage"),
                )
                reached_cache = history_complete[name] and bool(public_nodes) and new_items == 0
                cursor = page_info.get("endCursor") if isinstance(page_info, dict) else None
                if not has_next or reached_cache:
                    active[name] = False
                    cache["complete"][cache_keys[name]] = True
                    self._report_progress(
                        labels[name],
                        completed=pages[name],
                        total=pages[name],
                    )
                elif not isinstance(cursor, str) or not cursor:
                    active[name] = False
                    self._report_progress(
                        labels[name],
                        completed=pages[name],
                        total=pages[name],
                    )
                else:
                    cursors[name] = cursor

            if request_count % 10 == 0:
                for name, cache_key in cache_keys.items():
                    cache[cache_key] = items[name]
                self._checkpoint_cache(cache)

        return items["issues"], items["pullRequests"], items["issueComments"]

    def _refresh_mutable_items(
        self,
        *,
        issues: dict[str, dict[str, Any]],
        pull_requests: dict[str, dict[str, Any]],
    ) -> None:
        recent_cutoff = datetime.now(UTC) - timedelta(days=30)

        def mutable(node: dict[str, Any]) -> bool:
            closed_at = node.get("closedAt")
            if closed_at is None:
                return True
            if not isinstance(closed_at, str):
                return False
            try:
                return _parse_datetime(closed_at) >= recent_cutoff
            except ValueError:
                return False

        mutable_ids = [node_id for node_id, node in issues.items() if mutable(node)]
        mutable_ids.extend(
            node_id for node_id, node in pull_requests.items() if node.get("merged") is not True and mutable(node)
        )
        if not mutable_ids:
            return
        query = """
query RefreshOpenItems($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Issue { id closedAt }
    ... on PullRequest { id state closedAt merged mergedAt }
  }
}
"""
        for offset in range(0, len(mutable_ids), 100):
            chunk = mutable_ids[offset : offset + 100]
            response = self._request_graphql(
                query,
                variables={"ids": chunk},
                operation=f"status for {len(chunk)} mutable items",
            )
            data = response.get("data")
            nodes = data.get("nodes") if isinstance(data, dict) else None
            if not isinstance(nodes, list):
                continue
            for update in nodes:
                if not isinstance(update, dict) or not isinstance(
                    update.get("id"),
                    str,
                ):
                    continue
                node_id = update["id"]
                target = issues.get(node_id) or pull_requests.get(node_id)
                if target is not None:
                    target.update(update)

    def _collect_commit_years(
        self,
        *,
        user: str,
        cached_years: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        years_query = """
query ContributionYears($login: String!) {
  user(login: $login) { contributionsCollection { contributionYears } }
}
"""
        response = self._request_graphql(
            years_query,
            variables={"login": user},
            operation=f"contribution years for {user}",
        )
        data = response.get("data")
        account = data.get("user") if isinstance(data, dict) else None
        collection = account.get("contributionsCollection") if isinstance(account, dict) else None
        raw_years = collection.get("contributionYears") if isinstance(collection, dict) else None
        years = [year for year in raw_years if isinstance(year, int)] if isinstance(raw_years, list) else []

        query = """
query CommitContributions($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate }
        early: contributions(first: 100) {
          totalCount
          nodes { occurredAt commitCount }
        }
        recent: contributions(last: 100) {
          nodes { occurredAt commitCount }
        }
      }
    }
  }
}
"""
        current_year = datetime.now(UTC).year
        result = dict(cached_years)
        for year in sorted(years):
            key = str(year)
            if year != current_year and key in result:
                continue
            start = f"{year}-01-01T00:00:00Z"
            end = f"{year}-12-31T23:59:59Z"
            response = self._request_graphql(
                query,
                variables={"login": user, "from": start, "to": end},
                operation=f"commit contributions for {year}",
            )
            data = response.get("data")
            account = data.get("user") if isinstance(data, dict) else None
            collection = account.get("contributionsCollection") if isinstance(account, dict) else None
            groups = collection.get("commitContributionsByRepository") if isinstance(collection, dict) else None
            records: dict[str, dict[str, Any]] = {}
            if isinstance(groups, list):
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    repository = group.get("repository")
                    repository_name = repository.get("nameWithOwner") if isinstance(repository, dict) else None
                    if not isinstance(repository_name, str) or repository.get("isPrivate") is not False:
                        continue
                    for connection_name in ("early", "recent"):
                        connection = group.get(connection_name)
                        nodes = connection.get("nodes") if isinstance(connection, dict) else None
                        if not isinstance(nodes, list):
                            continue
                        for node in nodes:
                            if not isinstance(node, dict) or not isinstance(
                                node.get("occurredAt"),
                                str,
                            ):
                                continue
                            record = {
                                **node,
                                "repository": repository_name,
                                "isPrivate": False,
                            }
                            records[f"{repository_name}:{node['occurredAt']}"] = record
                    early = group.get("early")
                    total_count = early.get("totalCount") if isinstance(early, dict) else None
                    repository_records = sum(
                        1 for record in records.values() if record["repository"] == repository_name
                    )
                    if isinstance(total_count, int) and total_count > repository_records:
                        _logger.warning(
                            "GitHub truncated commit-day history for %s in %s (%s of %s days).",
                            repository_name,
                            year,
                            repository_records,
                            total_count,
                        )
            result[key] = list(records.values())
        return result

    def _commit_repositories(
        self,
        commit_years: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        totals: dict[str, int] = {}
        for records in commit_years.values():
            for record in records:
                repository = record.get("repository")
                count = record.get("commitCount")
                if isinstance(repository, str) and isinstance(count, int) and record.get("isPrivate") is False:
                    totals[repository] = totals.get(repository, 0) + count
        return sorted(totals, key=lambda name: (-totals[name], name))

    def _validate_public_repositories(
        self,
        repositories: list[str],
        *,
        cache: dict[str, Any],
    ) -> dict[str, tuple[str, str | None]]:
        if not repositories:
            return {}
        validated: dict[str, tuple[str, str | None]] = {}
        for offset in range(0, len(repositories), _REPOSITORY_METADATA_BATCH_SIZE):
            batch = repositories[offset : offset + _REPOSITORY_METADATA_BATCH_SIZE]
            definitions = []
            fields = []
            variables: dict[str, Any] = {}
            for index, repository in enumerate(batch):
                owner, name = repository.split("/", 1)
                definitions.extend(
                    (f"$owner{index}: String!", f"$name{index}: String!"),
                )
                variables[f"owner{index}"] = owner
                variables[f"name{index}"] = name
                fields.append(
                    f"r{index}: repository(owner: $owner{index}, name: $name{index}) "
                    "{ nameWithOwner isPrivate defaultBranchRef { name } }",
                )
            query = "query RepositoryMetadata(" + ", ".join(definitions) + ") { " + " ".join(fields) + " }"
            response = self._request_graphql(
                query,
                variables=variables,
                operation=f"public metadata for {len(batch)} local repositories",
                allow_partial=True,
            )
            data = response.get("data")
            if not isinstance(data, dict):
                continue
            for index, repository in enumerate(batch):
                repository_data = data.get(f"r{index}")
                if isinstance(repository_data, dict) and repository_data.get("isPrivate") is False:
                    default_ref = repository_data.get("defaultBranchRef")
                    default_branch = (
                        default_ref.get("name")
                        if isinstance(default_ref, dict) and isinstance(default_ref.get("name"), str)
                        else None
                    )
                    canonical_name = repository_data.get("nameWithOwner")
                    if not isinstance(canonical_name, str):
                        canonical_name = repository
                    existing = _take_repository_cache(cache, repository)
                    validated[repository] = (canonical_name, default_branch)
                    cache["repository_metadata"][canonical_name] = {
                        "isPrivate": False,
                        "defaultBranch": default_branch,
                    }
                    existing_local_state = existing.get("local_repositories")
                    if isinstance(existing_local_state, dict):
                        cache["local_repositories"][canonical_name] = existing_local_state
                    existing_commits = existing.get("commit_summaries")
                    if isinstance(existing_commits, dict):
                        cache["commit_summaries"][canonical_name] = existing_commits
                else:
                    _purge_repository_cache(cache, repository)
        self._mark_cache_updated(cache, "repository_metadata")
        self._checkpoint_cache(cache)
        return validated

    def _collect_commit_summaries(
        self,
        *,
        user: str,
        repositories: list[str],
        cache: dict[str, Any],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        if not repositories:
            return {}
        user_id = cache.get("user_id")
        if not isinstance(user_id, str):
            response = self._request_graphql(
                "query UserId($login: String!) { user(login: $login) { id } }",
                variables={"login": user},
                operation=f"GitHub identity for {user}",
            )
            data = response.get("data")
            account = data.get("user") if isinstance(data, dict) else None
            user_id = account.get("id") if isinstance(account, dict) else None
            if not isinstance(user_id, str):
                _logger.warning("Could not resolve commit identity for %s.", user)
                return {}
            cache["user_id"] = user_id

        result: dict[str, dict[str, dict[str, Any]]] = {
            repository: {
                oid: record
                for oid, record in cache["commit_summaries"].get(repository, {}).items()
                if isinstance(record, dict) and record.get("source") != "local"
            }
            for repository in repositories
        }
        operation = f"commit summaries from {len(repositories)} public repositories"
        requests = 0
        for batch_offset in range(0, len(repositories), _COMMIT_REPOSITORY_BATCH_SIZE):
            batch = repositories[batch_offset : batch_offset + _COMMIT_REPOSITORY_BATCH_SIZE]
            active = set(batch)
            cursors: dict[str, str | None] = dict.fromkeys(batch)
            pages = dict.fromkeys(batch, 0)
            had_cache = {repository: bool(result[repository]) for repository in batch}
            while active:
                current = [repository for repository in batch if repository in active]
                definitions = ["$author: ID!"]
                fields = []
                variables: dict[str, Any] = {"author": user_id}
                for index, repository in enumerate(current):
                    owner, name = repository.split("/", 1)
                    definitions.extend(
                        (
                            f"$owner{index}: String!",
                            f"$name{index}: String!",
                            f"$after{index}: String",
                        ),
                    )
                    variables[f"owner{index}"] = owner
                    variables[f"name{index}"] = name
                    variables[f"after{index}"] = cursors[repository]
                    fields.append(
                        f"""
  r{index}: repository(owner: $owner{index}, name: $name{index}) {{
    nameWithOwner isPrivate
    defaultBranchRef {{
      target {{
        ... on Commit {{
          history(first: {_COMMIT_PAGE_SIZE}, after: $after{index}, author: {{id: $author}}) {{
            pageInfo {{ hasNextPage endCursor }}
            nodes {{ oid messageHeadline committedDate url parents(first: 2) {{ totalCount }} }}
          }}
        }}
      }}
    }}
  }}
""",
                    )
                query = "query CommitSummaries(" + ", ".join(definitions) + ") {\n" + "".join(fields) + "}\n"
                self._report_progress(operation, completed=requests, total=None)
                response = self._request_graphql(
                    query,
                    variables=variables,
                    operation=f"{operation}, batch {batch_offset // _COMMIT_REPOSITORY_BATCH_SIZE + 1}",
                    allow_partial=True,
                )
                requests += 1
                data = response.get("data")
                if not isinstance(data, dict):
                    break
                for index, repository in enumerate(current):
                    repository_data = data.get(f"r{index}")
                    if not isinstance(repository_data, dict) or repository_data.get("isPrivate") is not False:
                        result.pop(repository, None)
                        active.discard(repository)
                        continue
                    branch = repository_data.get("defaultBranchRef")
                    target = branch.get("target") if isinstance(branch, dict) else None
                    history = target.get("history") if isinstance(target, dict) else None
                    if not isinstance(history, dict):
                        active.discard(repository)
                        continue
                    nodes = history.get("nodes")
                    page_nodes = [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []
                    reached_cache = False
                    for node in page_nodes:
                        oid = node.get("oid")
                        headline = node.get("messageHeadline")
                        committed_at = node.get("committedDate")
                        url = node.get("url")
                        parents = node.get("parents")
                        if not all(isinstance(value, str) for value in (oid, headline, committed_at, url)):
                            continue
                        if oid in result[repository]:
                            reached_cache = True
                        result[repository][oid] = {
                            "oid": oid,
                            "headline": headline,
                            "committedAt": committed_at,
                            "url": url,
                            "repository": repository,
                            "isPrivate": False,
                            "source": "github",
                            "historyComplete": False,
                            "isMerge": (
                                parents.get("totalCount", 0) > 1
                                if isinstance(parents, dict) and isinstance(parents.get("totalCount"), int)
                                else None
                            ),
                        }
                    pages[repository] += 1
                    page_info = history.get("pageInfo")
                    has_next = isinstance(page_info, dict) and bool(
                        page_info.get("hasNextPage"),
                    )
                    cursor = page_info.get("endCursor") if isinstance(page_info, dict) else None
                    initial_sample_complete = not had_cache[repository] and pages[repository] >= 1
                    incremental_limit = pages[repository] >= _MAX_INCREMENTAL_COMMIT_PAGES
                    if (
                        not has_next
                        or reached_cache
                        or initial_sample_complete
                        or incremental_limit
                        or not isinstance(cursor, str)
                        or not cursor
                    ):
                        active.discard(repository)
                    else:
                        cursors[repository] = cursor
                cache["commit_summaries"] = result
                self._checkpoint_cache(cache)
                self._report_progress(operation, completed=requests, total=None)
        self._report_progress(operation, completed=requests, total=requests)
        return result

    def _is_in_scope(
        self,
        repository: str,
        *,
        organizations: list[str],
        include_repositories: list[str],
        exclude_repositories: list[str],
    ) -> bool:
        normalized = repository.lower()
        if normalized in {name.lower() for name in exclude_repositories}:
            return False
        if not organizations and not include_repositories:
            return True
        if normalized in {name.lower() for name in include_repositories}:
            return True
        owner = normalized.split("/", 1)[0] if "/" in normalized else ""
        return owner in {organization.lower() for organization in organizations}

    def _scope_labels(
        self,
        *,
        organizations: list[str],
        include_repositories: list[str],
        exclude_repositories: list[str],
    ) -> list[str]:
        labels = [
            *(f"org:{org}" for org in organizations),
            *(f"repo:{repo}" for repo in include_repositories),
        ]
        if not labels:
            labels.append("all repositories")
        labels.extend(f"-repo:{repo}" for repo in exclude_repositories)
        return labels

    def _get_authenticated_user(self) -> str:
        query = "query Viewer { viewer { login } }"
        response = self._request_graphql(
            query,
            variables={},
            operation="authenticated GitHub account",
        )
        data = response.get("data")
        viewer = data.get("viewer") if isinstance(data, dict) else None
        if not isinstance(viewer, dict) or "login" not in viewer:
            raise RuntimeError("Could not resolve the GitHub CLI's authenticated user.")
        return str(viewer["login"])

    def _collect_activity(
        self,
        *,
        user: str,
        organizations: list[str],
        include_repositories: list[str],
        exclude_repositories: list[str],
        repositories_dirs: list[Path] | None = None,
        commit_author_emails: list[str] | None = None,
        use_configured_identity: bool = False,
    ) -> _CollectedActivity:
        cache = _load_cache(user, cache_dir=self._cache_dir)
        self._strip_private_cache(cache)
        # Persist the current schema immediately so an older cache containing
        # private metadata is purged even if the subsequent request fails.
        self._checkpoint_cache(cache)
        if self._cache_is_fresh(cache, "activity"):
            _logger.info("Using recently cached issue, pull request, and comment data.")
            issues = cache["issues"]
            pull_requests = cache["pull_requests"]
            comments = cache["comments"]
        else:
            issues, pull_requests, comments = self._collect_core_activity(
                user=user,
                cache=cache,
            )
            cache.update(
                issues=issues,
                pull_requests=pull_requests,
                comments=comments,
            )
            self._mark_cache_updated(cache, "activity")
            self._checkpoint_cache(cache)

        if self._cache_is_fresh(cache, "statuses"):
            _logger.info("Using recently cached issue and pull request statuses.")
        else:
            self._refresh_mutable_items(issues=issues, pull_requests=pull_requests)
            self._mark_cache_updated(cache, "statuses")
            self._checkpoint_cache(cache)

        if self._cache_is_fresh(cache, "commits"):
            _logger.info("Using recently cached commit contribution data.")
            commit_years = cache["commit_years"]
        else:
            commit_years = self._collect_commit_years(
                user=user,
                cached_years=cache["commit_years"],
            )
            self._mark_cache_updated(cache, "commits")
        cache.update(
            issues=issues,
            pull_requests=pull_requests,
            comments=comments,
            commit_years=commit_years,
        )
        self._checkpoint_cache(cache)

        scoped_commit_repositories = [
            repository
            for repository in self._commit_repositories(commit_years)
            if self._is_in_scope(
                repository,
                organizations=organizations,
                include_repositories=include_repositories,
                exclude_repositories=exclude_repositories,
            )
        ]

        local_records: dict[str, dict[str, dict[str, Any]]] = {}
        local_repositories: set[str] = set()
        if repositories_dirs:
            local_remotes = _discover_local_remotes(
                repositories_dirs,
                known_repositories=scoped_commit_repositories,
                progress_callback=self._progress_callback,
            )
            local_remotes = [
                remote
                for remote in local_remotes
                if self._is_in_scope(
                    remote.repository,
                    organizations=organizations,
                    include_repositories=include_repositories,
                    exclude_repositories=exclude_repositories,
                )
            ]
            matched_repositories = []
            seen_repositories: set[str] = set()
            for remote in local_remotes:
                normalized = remote.repository.lower()
                if normalized not in seen_repositories:
                    matched_repositories.append(remote.repository)
                    seen_repositories.add(normalized)
            _logger.info(
                "Found %s scoped GitHub repositories in local clones.",
                len(matched_repositories),
            )
            public_metadata = self._validate_public_repositories(
                matched_repositories,
                cache=cache,
            )
            default_branches = dict(public_metadata.values())
            remotes_by_path: dict[Path, _LocalRemote] = {}
            for remote in local_remotes:
                metadata = public_metadata.get(remote.repository)
                if metadata is None:
                    continue
                canonical_name, _ = metadata
                canonical_remote = _LocalRemote(
                    path=remote.path,
                    remote=remote.remote,
                    repository=canonical_name,
                )
                path = remote.path.resolve()
                remotes_by_path.setdefault(path, canonical_remote)
            local_result = _collect_local_commit_summaries(
                list(remotes_by_path.values()),
                default_branches=default_branches,
                login=user,
                explicit_emails=commit_author_emails or [],
                use_configured_identity=use_configured_identity,
                cache=cache,
                progress_callback=self._progress_callback,
            )
            local_records = local_result.records
            local_repositories = local_result.repositories
            self._checkpoint_cache(cache)

        commit_repositories = [
            repository for repository in scoped_commit_repositories if repository not in local_repositories
        ][:_MAX_COMMIT_REPOSITORIES]
        summaries_cached = all(repository in cache["commit_summaries"] for repository in commit_repositories)
        if self._cache_is_fresh(cache, "commit_summaries") and summaries_cached:
            _logger.info("Using recently cached public commit summaries.")
            github_records = {
                repository: {
                    oid: record
                    for oid, record in cache["commit_summaries"][repository].items()
                    if isinstance(record, dict) and record.get("source") != "local"
                }
                for repository in commit_repositories
            }
        else:
            github_records = self._collect_commit_summaries(
                user=user,
                repositories=commit_repositories,
                cache=cache,
            )
            self._mark_cache_updated(cache, "commit_summaries")
            cache["commit_summaries"].update(github_records)
            self._checkpoint_cache(cache)
        commit_summary_records = {**github_records, **local_records}

        events: list[_ActivityEvent] = []

        def in_scope(repository: object) -> bool:
            return isinstance(repository, str) and self._is_in_scope(
                repository,
                organizations=organizations,
                include_repositories=include_repositories,
                exclude_repositories=exclude_repositories,
            )

        def metadata(node: dict[str, Any]) -> dict[str, Any]:
            author = node.get("author")
            return {
                "title": node.get("title") if isinstance(node.get("title"), str) else None,
                "url": node.get("url") if isinstance(node.get("url"), str) else None,
                "number": node.get("number") if isinstance(node.get("number"), int) else None,
                "subject_author": author.get("login")
                if isinstance(author, dict) and isinstance(author.get("login"), str)
                else None,
            }

        for issue in issues.values():
            repository = issue.get("repository")
            repository_name = repository.get("nameWithOwner") if isinstance(repository, dict) else None
            if not isinstance(repository_name, str) or not in_scope(repository_name):
                continue
            if isinstance(issue.get("createdAt"), str):
                events.append(
                    _ActivityEvent(
                        category="opened_issues",
                        occurred_at=_parse_datetime(issue["createdAt"]),
                        repository=repository_name,
                        subject_type="issue",
                        **metadata(issue),
                    ),
                )
            if isinstance(issue.get("closedAt"), str):
                events.append(
                    _ActivityEvent(
                        category="closed_issues",
                        occurred_at=_parse_datetime(issue["closedAt"]),
                        repository=repository_name,
                        subject_type="issue",
                        **metadata(issue),
                    ),
                )

        for pr in pull_requests.values():
            repository = pr.get("repository")
            repository_name = repository.get("nameWithOwner") if isinstance(repository, dict) else None
            if not isinstance(repository_name, str) or not in_scope(repository_name):
                continue
            if isinstance(pr.get("createdAt"), str):
                events.append(
                    _ActivityEvent(
                        category="opened_prs",
                        occurred_at=_parse_datetime(pr["createdAt"]),
                        repository=repository_name,
                        subject_type="pull_request",
                        **metadata(pr),
                    ),
                )
            if pr.get("merged") is True and isinstance(pr.get("mergedAt"), str):
                events.append(
                    _ActivityEvent(
                        category="merged_prs",
                        occurred_at=_parse_datetime(pr["mergedAt"]),
                        repository=repository_name,
                        subject_type="pull_request",
                        **metadata(pr),
                    ),
                )
            elif pr.get("state") == "CLOSED" and isinstance(pr.get("closedAt"), str):
                events.append(
                    _ActivityEvent(
                        category="closed_prs",
                        occurred_at=_parse_datetime(pr["closedAt"]),
                        repository=repository_name,
                        subject_type="pull_request",
                        **metadata(pr),
                    ),
                )

        for comment in comments.values():
            pull_request = comment.get("pullRequest")
            issue = comment.get("issue")
            subject = pull_request if isinstance(pull_request, dict) else issue
            repository = subject.get("repository") if isinstance(subject, dict) else None
            repository_name = repository.get("nameWithOwner") if isinstance(repository, dict) else None
            if (
                isinstance(repository_name, str)
                and in_scope(repository_name)
                and isinstance(subject, dict)
                and isinstance(comment.get("createdAt"), str)
            ):
                events.append(
                    _ActivityEvent(
                        category="comments",
                        occurred_at=_parse_datetime(comment["createdAt"]),
                        repository=repository_name,
                        subject_type=("pull_request" if isinstance(pull_request, dict) else "issue"),
                        **metadata(subject),
                    ),
                )

        for records in commit_years.values():
            for record in records:
                if not isinstance(record, dict) or not in_scope(
                    record.get("repository"),
                ):
                    continue
                occurred_at = record.get("occurredAt")
                commit_count = record.get("commitCount")
                if isinstance(occurred_at, str) and isinstance(commit_count, int):
                    repository = record["repository"]
                    events.append(
                        _ActivityEvent(
                            category="commits",
                            occurred_at=_parse_datetime(occurred_at),
                            repository=repository,
                            count=commit_count,
                            title=f"Commits in {repository}",
                            url=f"https://github.com/{repository}",
                            subject_type="repository",
                        ),
                    )

        _logger.info(
            "Activity totals: %s",
            {
                category: sum(event.count for event in events if event.category == category)
                for category in sorted({event.category for event in events})
            },
        )
        commit_summaries = []
        for repository, records in commit_summary_records.items():
            for record in records.values():
                oid = record.get("oid")
                headline = record.get("headline")
                committed_at = record.get("committedAt")
                url = record.get("url")
                if (
                    isinstance(oid, str)
                    and isinstance(headline, str)
                    and isinstance(committed_at, str)
                    and isinstance(url, str)
                    and record.get("isPrivate") is False
                ):
                    commit_summaries.append(
                        _CommitSummary(
                            oid=oid,
                            headline=headline,
                            committed_at=_parse_datetime(committed_at),
                            repository=repository,
                            url=url,
                            source=(record["source"] if record.get("source") in {"github", "local"} else "github"),
                            history_complete=record.get("historyComplete") is True,
                            is_merge=(record["isMerge"] if isinstance(record.get("isMerge"), bool) else None),
                        ),
                    )
        _logger.info("Analyzing %s cached commit summaries.", len(commit_summaries))
        return _CollectedActivity(events=events, commits=commit_summaries)

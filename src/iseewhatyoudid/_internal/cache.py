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
from typing import TYPE_CHECKING, Any

from platformdirs import user_cache_path

if TYPE_CHECKING:
    from pathlib import Path


_CACHE_VERSION = 6


def _empty_cache(user: str) -> dict[str, Any]:
    return {
        "version": _CACHE_VERSION,
        "user": user,
        "user_id": None,
        "complete": {
            "issues": False,
            "pull_requests": False,
            "comments": False,
        },
        "updated_at": {},
        "issues": {},
        "pull_requests": {},
        "comments": {},
        "commit_years": {},
        "commit_summaries": {},
        "local_repositories": {},
        "repository_metadata": {},
    }


def _cache_path(user: str, *, cache_dir: Path | None = None) -> Path:
    root = cache_dir or user_cache_path("iseewhatyoudid")
    safe_user = "".join(character if character.isalnum() or character in "-." else "_" for character in user)
    return root / f"{safe_user}.json"


def _load_cache(user: str, *, cache_dir: Path | None = None) -> dict[str, Any]:
    path = _cache_path(user, cache_dir=cache_dir)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _empty_cache(user)
    if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION or data.get("user") != user:
        return _empty_cache(user)
    empty = _empty_cache(user)
    for key in (
        "updated_at",
        "issues",
        "pull_requests",
        "comments",
        "commit_years",
        "commit_summaries",
        "local_repositories",
        "repository_metadata",
    ):
        if isinstance(data.get(key), dict):
            empty[key] = data[key]
    if isinstance(data.get("user_id"), str):
        empty["user_id"] = data["user_id"]
    complete = data.get("complete")
    if isinstance(complete, dict):
        for key in empty["complete"]:
            if isinstance(complete.get(key), bool):
                empty["complete"][key] = complete[key]
    return empty


def _save_cache(data: dict[str, Any], *, cache_dir: Path | None = None) -> None:
    user = str(data["user"])
    path = _cache_path(user, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)

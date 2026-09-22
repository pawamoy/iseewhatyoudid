from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path

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
    safe_user = "".join(
        character if character.isalnum() or character in "-." else "_"
        for character in user
    )
    return root / f"{safe_user}.json"


def _load_cache(user: str, *, cache_dir: Path | None = None) -> dict[str, Any]:
    path = _cache_path(user, cache_dir=cache_dir)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _empty_cache(user)
    if (
        not isinstance(data, dict)
        or data.get("version") != _CACHE_VERSION
        or data.get("user") != user
    ):
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

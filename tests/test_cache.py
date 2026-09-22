"""Tests for the local activity cache."""

from __future__ import annotations

from pathlib import Path

from iseewhatyoudid._internal.cache import _load_cache, _save_cache


def test_cache_round_trip(tmp_path: Path) -> None:
    """Cached activity is stored per user and loaded again."""
    data = _load_cache("octocat", cache_dir=tmp_path)
    data["comments"]["comment-1"] = {
        "id": "comment-1",
        "createdAt": "2026-01-01T00:00:00Z",
    }

    _save_cache(data, cache_dir=tmp_path)

    assert _load_cache("octocat", cache_dir=tmp_path) == data
    assert (tmp_path / "octocat.json").stat().st_mode & 0o777 == 0o600

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

"""Tests for the CLI."""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from rich.logging import RichHandler

from iseewhatyoudid import main
from iseewhatyoudid._internal import cli
from iseewhatyoudid._internal import debug
from iseewhatyoudid._internal.activity import _CollectedActivity


def test_main() -> None:
    """Basic CLI test."""
    assert main([]) == 0


def test_show_help(capsys: pytest.CaptureFixture) -> None:
    """Show help.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["-h"])
    captured = capsys.readouterr()
    assert "iseewhatyoudid" in captured.out


def test_show_version(capsys: pytest.CaptureFixture) -> None:
    """Show version.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert debug._get_version() in captured.out


def test_show_debug_info(capsys: pytest.CaptureFixture) -> None:
    """Show debug information.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["--debug-info"])
    captured = capsys.readouterr().out.lower()
    assert "python" in captured
    assert "system" in captured
    assert "environment" in captured
    assert "packages" in captured


def test_dashboard_rejects_raw_token_options() -> None:
    """Dashboard authentication is delegated to GitHub CLI."""
    with pytest.raises(SystemExit):
        main(["dashboard", "--token", "secret"])


def test_dashboard_accepts_repeatable_local_commit_options() -> None:
    """Local roots and author identities can be supplied more than once."""
    options = cli.get_parser().parse_args(
        [
            "dashboard",
            "--repos-dir",
            "projects",
            "--repos-dir",
            "work",
            "--commit-author-email",
            "first@example.com",
            "--commit-author-email",
            "second@example.com",
        ]
    )

    assert options.repos_dir == [Path("projects"), Path("work")]
    assert options.commit_author_email == [
        "first@example.com",
        "second@example.com",
    ]


@pytest.mark.parametrize(
    ("verbose", "log_level", "expected"),
    [
        (0, None, logging.CRITICAL + 1),
        (1, None, logging.INFO),
        (2, None, logging.DEBUG),
        (0, "warning", logging.WARNING),
    ],
)
def test_logging_is_pretty_and_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    verbose: int,
    log_level: str | None,
    expected: int,
) -> None:
    """Logging is silent by default and rendered by Rich when requested."""
    configured: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli.logging,
        "basicConfig",
        lambda **kwargs: configured.append(kwargs),
    )

    cli._configure_logging(
        verbose=verbose,
        log_level=log_level,
        console=Console(file=StringIO()),
    )

    assert configured[0]["level"] == expected
    handlers = configured[0]["handlers"]
    assert isinstance(handlers, list)
    assert len(handlers) == 1
    assert isinstance(handlers[0], RichHandler)
    assert handlers[0].level == expected


def test_dashboard_without_scope_uses_all_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authenticated user's full activity is the default dashboard scope."""
    collected_options: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs: object) -> None:  # noqa: ARG002
            pass

        def _get_authenticated_user(self) -> str:
            return "octocat"

        def _scope_labels(self, **kwargs: object) -> list[str]:  # noqa: ARG002
            return ["all repositories"]

        def _collect_activity(
            self,
            **kwargs: object,
        ) -> _CollectedActivity:
            collected_options.update(kwargs)
            return _CollectedActivity(events=[], commits=[])

    monkeypatch.setattr(cli, "_GitHubClient", _Client)
    monkeypatch.setattr(cli, "_write_dashboard_html", lambda **kwargs: None)

    assert main(["dashboard"]) == 0
    assert collected_options["repositories_dirs"] == []
    assert collected_options["commit_author_emails"] == []
    assert collected_options["use_configured_identity"] is True

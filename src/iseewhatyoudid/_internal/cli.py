# Why does this file exist, and why not put this in `__main__`?
#
# You might be tempted to import things from `__main__` later,
# but that will cause problems: the code will get executed twice:
#
# - When you run `python -m iseewhatyoudid` python will execute
#   `__main__.py` as a script. That means there won't be any
#   `iseewhatyoudid.__main__` in `sys.modules`.
# - When you import `__main__` it will get executed again (as a module) because
#   there's no `iseewhatyoudid.__main__` in `sys.modules`.

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from iseewhatyoudid._internal.activity import _aggregate_activity
from iseewhatyoudid._internal import debug
from iseewhatyoudid._internal.github_api import _GitHubClient
from iseewhatyoudid._internal.html_render import _write_dashboard_html


def _configure_logging(
    *, verbose: int, log_level: str | None, console: Console
) -> None:
    if log_level is not None:
        level = getattr(logging, log_level.upper())
    elif verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    else:
        level = logging.CRITICAL + 1
    handler = RichHandler(
        console=console,
        level=level,
        markup=True,
        rich_tracebacks=True,
        show_path=level <= logging.DEBUG,
        show_time=False,
    )
    logging.basicConfig(
        force=True,
        format="%(message)s",
        handlers=[handler],
        level=level,
    )


class _DebugInfo(argparse.Action):
    def __init__(self, nargs: int | str | None = 0, **kwargs: Any) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        debug._print_debug_info()
        sys.exit(0)


def _add_dashboard_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user", help="GitHub username. Defaults to authenticated user."
    )
    parser.add_argument(
        "--org",
        action="append",
        default=[],
        help="Organization name to include all repositories from. Can be used multiple times.",
    )
    parser.add_argument(
        "--include-repo",
        action="append",
        default=[],
        help="Repository to include (`owner/name`). Can be used multiple times.",
    )
    parser.add_argument(
        "--exclude-repo",
        action="append",
        default=[],
        help="Repository to exclude (`owner/name`). Can be used multiple times.",
    )
    parser.add_argument(
        "--repos-dir",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help=(
            "Discover local clones below PATH and read their public default-branch "
            "commit history without fetching. Can be used multiple times."
        ),
    )
    parser.add_argument(
        "--commit-author-email",
        action="append",
        default=[],
        metavar="EMAIL",
        help=(
            "Include local commits authored with EMAIL. Can be used multiple times; "
            "the authenticated user's configured Git email is included automatically."
        ),
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        metavar="PATH",
        default=Path("iseewhatyoudid.html"),
        help="Write the interactive HTML dashboard to PATH. Defaults to `iseewhatyoudid.html`.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass the short-lived cache and fetch the latest GitHub data.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: info, -vv: debug).",
    )
    parser.add_argument(
        "--log-level",
        choices=["critical", "error", "warning", "info", "debug"],
        default=None,
        help="Enable logging at an explicit level.",
    )


def _run_dashboard(opts: argparse.Namespace) -> int:
    console = Console(stderr=True)
    _configure_logging(
        verbose=opts.verbose,
        log_level=opts.log_level,
        console=console,
    )

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task_ids: dict[str, TaskID] = {}

            def _update_progress(
                operation: str, completed: int, total: int | None
            ) -> None:
                description = f"Fetching {operation}"
                if operation not in task_ids:
                    task_ids[operation] = progress.add_task(
                        description, total=total, completed=completed
                    )
                else:
                    progress.update(
                        task_ids[operation], completed=completed, total=total
                    )

            client = _GitHubClient(
                progress_callback=_update_progress,
                force_refresh=opts.refresh,
            )
            explicit_user = opts.user is not None
            user = opts.user
            if not user:
                authentication_task = progress.add_task(
                    "Checking GitHub authentication", total=None
                )
                user = client._get_authenticated_user()
                progress.update(authentication_task, total=1, completed=1)
            scope_labels = client._scope_labels(
                organizations=opts.org,
                include_repositories=opts.include_repo,
                exclude_repositories=opts.exclude_repo,
            )
            collected = client._collect_activity(
                user=user,
                organizations=opts.org,
                include_repositories=opts.include_repo,
                exclude_repositories=opts.exclude_repo,
                repositories_dirs=opts.repos_dir,
                commit_author_emails=opts.commit_author_email,
                use_configured_identity=not explicit_user,
            )
            aggregated = _aggregate_activity(collected.events)
    except RuntimeError as error:
        print(f"Activity collection error: {error}", file=sys.stderr)
        return 1

    try:
        _write_dashboard_html(
            aggregated=aggregated,
            user=user,
            scope=scope_labels,
            path=opts.output_html,
            events=collected.events,
            commits=collected.commits,
        )
    except OSError as error:
        print(f"Could not write HTML dashboard: {error}", file=sys.stderr)
        return 1
    print(f"Wrote HTML dashboard to {opts.output_html}", file=sys.stderr)
    return 0


def get_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser.

    Returns:
        An argparse parser.
    """
    parser = argparse.ArgumentParser(prog="iseewhatyoudid")
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {debug._get_version()}"
    )
    parser.add_argument(
        "--debug-info", action=_DebugInfo, help="Print debug information."
    )
    subparsers = parser.add_subparsers(dest="command")
    dashboard = subparsers.add_parser(
        "dashboard", help="Display your GitHub activity dashboard."
    )
    _add_dashboard_arguments(dashboard)
    return parser


def main(args: list[str] | None = None) -> int:
    """Run the main program.

    This function is executed when you type `iseewhatyoudid` or `python -m iseewhatyoudid`.

    Parameters:
        args: Arguments passed from the command line.

    Returns:
        An exit code.
    """
    parser = get_parser()
    opts = parser.parse_args(args=args)
    if not opts.command:
        parser.print_help()
        return 0

    if opts.command == "dashboard":
        return _run_dashboard(opts)

    parser.print_help()
    return 0

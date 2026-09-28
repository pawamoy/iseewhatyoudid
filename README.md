# iseewhatyoudid

[![ci](https://github.com/pawamoy/iseewhatyoudid/workflows/ci/badge.svg)](https://github.com/pawamoy/iseewhatyoudid/actions?query=workflow%3Aci)
[![documentation](https://img.shields.io/badge/docs-zensical-FF9100.svg?style=flat)](https://pawamoy.github.io/iseewhatyoudid/)
[![pypi version](https://img.shields.io/pypi/v/iseewhatyoudid.svg)](https://pypi.org/project/iseewhatyoudid/)
[![gitter](https://img.shields.io/badge/matrix-chat-4DB798.svg?style=flat)](https://app.gitter.im/#/room/#iseewhatyoudid:gitter.im)

`iseewhatyoudid` is a small reminder that your work adds up. When you are
feeling as though you have not done enough, it lets you look back over the
issues and pull requests you have contributed, step by step and over time.

It creates an interactive HTML dashboard of a GitHub user's activity: issues
and pull requests they opened, status changes on those items, issue and pull
request comments they wrote, and commit contributions. Activity is grouped by
year, month, week, and day across every visible repository by default.

## A gentle reminder, not a scorecard

This tool is intentionally a double-edged one. Seeing your past activity can
help you recognise work that was easy to forget. It can also reinforce a sense
of being unproductive when activity is low, when GitHub does not capture the
work you did, or when you are simply going through a quieter period.

Take the dashboard with a grain of salt. GitHub activity does not measure a
person's worth, pleasure, or happiness—and it is not a complete measure of
their work or impact. Rest, learning, care, conversations, planning, and work
away from GitHub all matter too.

## Installation

```bash
pip install iseewhatyoudid
```

With [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install iseewhatyoudid
```

Python 3.10 or later is required.

## Usage

By default, the dashboard shows all activity for the GitHub account
authenticated in `gh`.

```bash
iseewhatyoudid dashboard
```

Pass `--user` to inspect a different GitHub user. Repository scopes are
optional filters: an organization (`--org`) or an individual repository
(`--include-repo`).

```bash
iseewhatyoudid dashboard --user octocat --include-repo octo-org/example
```

To inspect all repositories in an organization:

```bash
iseewhatyoudid dashboard --user octocat --org octo-org
```

The command writes `iseewhatyoudid.html` in the current directory. Open it in a
browser to explore a personal history of how your work accumulated:

- a cumulative chart that only moves forward, with contribution milestones;
- a one-square-per-day activity tapestry;
- active-time, repository, conversation, and return-after-a-break insights;
- issue and pull-request lifecycle views;
- contribution variety, repository stewardship, and project exploration;
- personal records, first contributions, and yearly chapter cards;
- a long-term monthly rhythm; and
- links that help rediscover older issues and pull requests;
- commit-summary work types, including features, fixes, documentation, tests,
  refactoring, security, accessibility, CI, maintenance, and more;
- commit composition and cumulative work-type charts, a filterable commit
  heatmap, repository/type matrix, and project-role views;
- care-work summaries, milestones, maintenance seasons, recurring topics, and
  conventional-prefix coverage; and
- a searchable, linked commit-summary gallery plus locally derived personal
  insights.

The detailed stacked views for years, recent months, weeks, and days remain
available near the end of the report.

### Authentication

The command uses the [GitHub CLI](https://cli.github.com/) for authentication
and GraphQL requests. Install `gh` and sign in once before running the
dashboard. Its browser-based sign-in flow stores the credential in your system
credential store when one is available.

```bash
gh auth login
iseewhatyoudid dashboard --org my-organization
```

When no `--user` is given, the account authenticated in `gh` is used. Make
sure that account can access the repositories you include.

### Scoping and filtering

`--org`, `--include-repo`, and `--exclude-repo` can each be repeated. Without
an organization or included repository, all repositories are included.
Otherwise, included repositories are combined with organization repositories;
exclusions always take precedence.

```bash
# Activity in two organizations, plus one standalone repository.
iseewhatyoudid dashboard \
  --user octocat \
  --org octo-org \
  --org another-org \
  --include-repo someone/project \
  --exclude-repo octo-org/archived-project
```

Run `iseewhatyoudid dashboard --help` to see every option. While GitHub data
is loading, the command displays a progress bar with fetched and total page
counts. Logging is disabled by default. Add `-v` for Rich-formatted API logging,
`-vv` for debug logging, or use `--log-level` to enable an explicit logging
level. Add `--refresh` to bypass the short-lived cache when you need the very
latest data.

### Using local clones for deeper commit history

If your public repositories are already cloned below one or more directories,
point the dashboard at them with `--repos-dir`:

```bash
iseewhatyoudid dashboard --repos-dir ~/dev
```

The option can be repeated. The command recursively discovers Git clones,
normalizes each `origin` remote that points to `github.com` in the selected
scope, and asks GitHub for only its canonical repository name, privacy status,
and default-branch name. Other remotes—such as contributor forks added while
reviewing pull requests—are ignored. Repositories do not need to appear in
GitHub's contribution list to qualify.
Discovery continues into the selected directory when that directory is itself
a Git repository, so a Git-backed container of nested clones works as expected.
The command then reads the local default branch without fetching, checking out,
or changing the clone. Matched local histories replace commit-summary API
requests; unmatched repositories keep the bounded GitHub fallback.

For the authenticated user, commits match the repository's configured Git
email, GitHub's `<login>@users.noreply.github.com` forms, and mailmap aliases.
Add old or additional identities explicitly when needed:

```bash
iseewhatyoudid dashboard \
  --repos-dir ~/work \
  --repos-dir ~/projects \
  --commit-author-email old-address@example.com
```

`--commit-author-email` can also be repeated. When `--user` selects another
person, local Git configuration is deliberately not assumed to belong to that
person; pass their known author emails explicitly. GitHub noreply addresses
matching the selected login continue to work automatically.

### HTML dashboard

Use `--output-html` to choose a different destination for the dashboard.

```bash
iseewhatyoudid dashboard --output-html activity.html
```

The report uses [Chart.js](https://www.chartjs.org/) from its CDN, so opening
it requires network access. Hover over bars to inspect values or click legend
entries to show and hide activity categories. Summary cards show totals and
yearly/monthly averages, while a GitHub-style grid shows daily activity over
the last year.

### Cache

Activity is cached in the operating system's user cache directory, as resolved
by [`platformdirs`](https://platformdirs.readthedocs.io/). After the initial
history fetch, later runs request only the newest issue, pull request, and
comment pages, refresh items that are still open or were closed recently, reuse
completed commit years, and update the current year's commits. Merged pull
requests and items closed for more than 30 days are treated as stable. Results
fetched during the last 15 minutes are reused entirely, making quick dashboard
reruns local-only after the authenticated username has been resolved.

The cache stores only the GitHub IDs, timestamps, states, repository names,
titles, URLs, numbers, author logins, commit SHAs, and single-line commit
summaries needed to rebuild the dashboard and its rediscovery links. It does
not store comment bodies, issue descriptions, multi-line commit messages,
patches, file contents, credentials, or local filesystem paths. For a matched
local clone it additionally stores the repository's last inspected commit,
reference name, shallow status, and a one-way fingerprint of the author
identities so unchanged histories require no commit scan on the next run.

### Commit-summary collection

Local clones are the preferred source when `--repos-dir` is used. Full clones
provide up to the newest 2,000 matching commits from the locally available
default-branch history per repository. Shallow clones provide only the history
present on disk and are labeled as shallow in the dashboard. New descendants
are scanned incrementally from the previously cached head. Rewritten histories
and changed author identities are rescanned; unchanged shallow clones are
reused, while deepened clones are detected and rescanned. Commit records remain
cached by immutable SHA, and older records are trimmed when a repository
exceeds the 2,000-commit limit.

For repositories without a usable local clone, commit-summary analysis is
deliberately bounded so it does not turn dashboard generation into a remote
repository crawl. Within the selected dashboard scope, the collector ranks
public repositories using the contribution counts already available and
samples at most 20 repositories. Repositories are batched ten at a time in
GraphQL requests. The first import retrieves only the newest 100 default-branch
commits attributed to the selected GitHub user in each sampled repository.

Commits are cached by immutable SHA. A normal refresh requests the newest page
and stops as soon as it sees a cached SHA. If more than a full page of new
commits appeared since the previous run, it can follow at most three pages per
repository. The dashboard reports how many histories came from local clones,
how many were shallow, and how many used the bounded GitHub sample.

The classifier recognizes forgiving Conventional Commit-style prefixes such
as `feat`, `feature`, `fix`, `docs`, `test`, `tests`, `refactor`, `perf`,
`security`, `a11y`, `i18n`, `deps`, `ci`, `build`, `chore`, and `revert`, with
optional scopes such as `feat(parser): ...`. Unrecognized summaries stay in a
normal “Other” category; they are not treated as malformed.

Default merge subjects such as `Merge branch ...` and
`Merge pull request ...` are excluded from commit-summary analysis so routine
integration commits do not dominate work types or recurring themes. Custom
merge commit subjects remain part of the analysis.

Private repositories are excluded from the cache and dashboard. GitHub's
complete user-wide issue, pull-request, and comment connections do not support
a public-only filter, so an authenticated response can transiently contain
private nodes. The collector checks each repository's `isPrivate` flag and
discards those nodes before adding anything to its history maps or writing a
cache checkpoint. Private commit-contribution groups are discarded in the same
way. Older cache schemas are invalidated and overwritten before collection
starts.

## Current limitations

Closed and merged dates describe status changes on issues and pull requests
authored by the selected user; GitHub does not expose a global stream of items
that the user personally closed or merged. Comments include issue comments and
top-level pull-request conversation comments, but not inline review comments.

GitHub's contribution API returns commit activity from at most 100 repositories
per year. For unusually active single repositories, the dashboard combines the
first and last 100 commit-days returned by GitHub and warns when the API still
truncates the year.

Commit-summary analysis covers only public default branches. Local clones can
be stale until they are updated outside this program, and shallow clones omit
history that is absent from disk. The GitHub fallback can omit older commits
beyond its initial sample. Both sources omit unmerged branch commits and
commits no longer reachable after rebases or force-pushes. Commits whose author
email does not match a configured identity can also be absent, and squashed
commits may not correspond one-to-one with the user's original commits.

## Troubleshooting

- Install [GitHub CLI](https://cli.github.com/) and run `gh auth login` before
  using the dashboard.
- Check repository names use the `owner/name` form.
- If GitHub returns a rate-limit or permission error, check `gh auth status`
  and make sure the authenticated account can access the selected repositories.
- Run `iseewhatyoudid --debug-info` when reporting an environment issue.

## Sponsors

<!-- sponsors-start -->
<!-- sponsors-end -->

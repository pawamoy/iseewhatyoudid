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

<div id="premium-sponsors" style="text-align: center;">

<div id="bronze-sponsors"><b>Bronze sponsors</b><p>
<a href="https://www.nixtla.io/"><picture><source media="(prefers-color-scheme: light)" srcset="https://www.nixtla.io/img/logo/full-black.svg"><source media="(prefers-color-scheme: dark)" srcset="https://www.nixtla.io/img/logo/full-white.svg"><img alt="Nixtla" src="https://www.nixtla.io/img/logo/full-black.svg" style="height: 60px; "></picture></a><br>
</p></div>
</div>

---

<div id="sponsors"><p>
<a href="https://github.com/ofek"><img alt="ofek" src="https://avatars.githubusercontent.com/u/9677399?u=386c330f212ce467ce7119d9615c75d0e9b9f1ce&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/samuelcolvin"><img alt="samuelcolvin" src="https://avatars.githubusercontent.com/u/4039449?u=42eb3b833047c8c4b4f647a031eaef148c16d93f&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/tlambert03"><img alt="tlambert03" src="https://avatars.githubusercontent.com/u/1609449?u=922abf0524b47739b37095e553c99488814b05db&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ssbarnea"><img alt="ssbarnea" src="https://avatars.githubusercontent.com/u/102495?u=c7bd9ddf127785286fc939dd18cb02db0a453bce&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/femtomc"><img alt="femtomc" src="https://avatars.githubusercontent.com/u/34410036?u=f13a71daf2a9f0d2da189beaa94250daa629e2d8&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://fastapi.tiangolo.com/"><img alt="FastAPI" src="https://raw.githubusercontent.com/tiangolo/fastapi/master/docs/en/docs/img/logo-margin/logo-teal.png" style="height: 200px; "></a>
<a href="https://github.com/cmarqu"><img alt="cmarqu" src="https://avatars.githubusercontent.com/u/360986?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/kolenaIO"><img alt="kolenaIO" src="https://avatars.githubusercontent.com/u/77010818?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ramnes"><img alt="ramnes" src="https://avatars.githubusercontent.com/u/835072?u=3fca03c3ba0051e2eb652b1def2188a94d1e1dc2&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/machow"><img alt="machow" src="https://avatars.githubusercontent.com/u/2574498?u=c41e3d2f758a05102d8075e38d67b9c17d4189d7&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/BenHammersley"><img alt="BenHammersley" src="https://avatars.githubusercontent.com/u/99436?u=4499a7b507541045222ee28ae122dbe3c8d08ab5&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/trevorWieland"><img alt="trevorWieland" src="https://avatars.githubusercontent.com/u/28811461?u=74cc0e3756c1d4e3d66b5c396e1d131ea8a10472&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/MarcoGorelli"><img alt="MarcoGorelli" src="https://avatars.githubusercontent.com/u/33491632?u=7de3a749cac76a60baca9777baf71d043a4f884d&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/analog-cbarber"><img alt="analog-cbarber" src="https://avatars.githubusercontent.com/u/7408243?u=fe0e7bf2882d1c9c901a341c2502e1518466527a&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/OdinManiac"><img alt="OdinManiac" src="https://avatars.githubusercontent.com/u/22727172?u=36ab20970f7f52ae8e7eb67b7fcf491fee01ac22&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/rstudio-sponsorship"><img alt="rstudio-sponsorship" src="https://avatars.githubusercontent.com/u/58949051?u=0c471515dd18111be30dfb7669ed5e778970959b&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/schlich"><img alt="schlich" src="https://avatars.githubusercontent.com/u/21191435?u=6f1240adb68f21614d809ae52d66509f46b1e877&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/butterlyn"><img alt="butterlyn" src="https://avatars.githubusercontent.com/u/53323535?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/livingbio"><img alt="livingbio" src="https://avatars.githubusercontent.com/u/10329983?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/NemetschekAllplan"><img alt="NemetschekAllplan" src="https://avatars.githubusercontent.com/u/912034?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/EricJayHartman"><img alt="EricJayHartman" src="https://avatars.githubusercontent.com/u/9259499?u=7e58cc7ec0cd3e85b27aec33656aa0f6612706dd&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/15r10nk"><img alt="15r10nk" src="https://avatars.githubusercontent.com/u/44680962?u=f04826446ff165742efa81e314bd03bf1724d50e&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/activeloopai"><img alt="activeloopai" src="https://avatars.githubusercontent.com/u/34816118?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/roboflow"><img alt="roboflow" src="https://avatars.githubusercontent.com/u/53104118?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/RapidataAI"><img alt="RapidataAI" src="https://avatars.githubusercontent.com/u/104209891?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/rodolphebarbanneau"><img alt="rodolphebarbanneau" src="https://avatars.githubusercontent.com/u/46493454?u=6c405452a40c231cdf0b68e97544e07ee956a733&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/theSymbolSyndicate"><img alt="theSymbolSyndicate" src="https://avatars.githubusercontent.com/u/111542255?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/blakeNaccarato"><img alt="blakeNaccarato" src="https://avatars.githubusercontent.com/u/20692450?u=bb919218be30cfa994514f4cf39bb2f7cf952df4&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ChargeStorm"><img alt="ChargeStorm" src="https://avatars.githubusercontent.com/u/26000165?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/Cusp-AI"><img alt="Cusp-AI" src="https://avatars.githubusercontent.com/u/178170649?v=4" style="height: 32px; border-radius: 100%;"></a>
</p></div>


*And 4 more private sponsor(s).*

<!-- sponsors-end -->

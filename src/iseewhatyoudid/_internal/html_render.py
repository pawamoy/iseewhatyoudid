from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from iseewhatyoudid._internal.activity import _ActivityEvent, _Bucket, _CommitSummary
from iseewhatyoudid._internal.commit_analysis import _analyze_commits

_CATEGORY_META: tuple[tuple[str, str, str], ...] = (
    ("opened_issues", "Opened issues", "#06b6d4"),
    ("closed_issues", "Closed issues", "#22c55e"),
    ("opened_prs", "Opened PRs", "#eab308"),
    ("merged_prs", "Merged PRs", "#d946ef"),
    ("closed_prs", "Closed PRs", "#ef4444"),
    ("comments", "Comments", "#f97316"),
    ("commits", "Commits", "#3b82f6"),
)
_CATEGORY_LABELS = {category: label for category, label, _ in _CATEGORY_META}
_CATEGORY_COLORS = {category: color for category, _, color in _CATEGORY_META}
_SECTION_TITLES = {
    "years": "Your chapters by year",
    "months_last_12": "The last 12 months",
    "weeks_last_12": "The last 12 weeks",
    "days_last_30": "The last 30 days",
}


def _count_events(events: list[_ActivityEvent], category: str | None = None) -> int:
    return sum(
        event.count
        for event in events
        if category is None or event.category == category
    )


def _month_range(start: date, end: date) -> list[str]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _event_link(event: _ActivityEvent) -> dict[str, Any]:
    action = _CATEGORY_LABELS[event.category]
    title = event.title or event.repository
    if event.count > 1:
        action = f"{event.count} commits"
    return {
        "date": event.occurred_at.date().isoformat(),
        "action": action,
        "title": title,
        "repository": event.repository,
        "url": event.url,
    }


def _cumulative_data(events: list[_ActivityEvent]) -> dict[str, Any]:
    if not events:
        return {"labels": [], "datasets": []}
    first = min(event.occurred_at for event in events).date().replace(day=1)
    today = datetime.now(timezone.utc).date().replace(day=1)
    labels = _month_range(first, today)
    per_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        per_month[event.occurred_at.strftime("%Y-%m")][event.category] += event.count
    running = {category: 0 for category in _CATEGORY_LABELS}
    series = {category: [] for category in _CATEGORY_LABELS}
    for label in labels:
        for category in running:
            running[category] += per_month[label][category]
            series[category].append(running[category])
    return {
        "labels": labels,
        "datasets": [
            {
                "label": label,
                "data": series[category],
                "borderColor": color,
                "backgroundColor": f"{color}25",
                "fill": False,
                "pointRadius": 0,
                "borderWidth": 2,
                "tension": 0.2,
            }
            for category, label, color in _CATEGORY_META
        ],
    }


def _milestones(events: list[_ActivityEvent]) -> list[dict[str, Any]]:
    thresholds = (100, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000)
    milestones = []
    running = 0
    threshold_index = 0
    for event in sorted(events, key=lambda item: item.occurred_at):
        previous = running
        running += event.count
        while (
            threshold_index < len(thresholds)
            and previous < thresholds[threshold_index] <= running
        ):
            threshold = thresholds[threshold_index]
            milestones.append(
                {
                    "value": threshold,
                    "date": event.occurred_at.date().isoformat(),
                    "repository": event.repository,
                }
            )
            threshold_index += 1
    return milestones[-6:]


def _lifecycle(events: list[_ActivityEvent]) -> dict[str, Any]:
    def key(event: _ActivityEvent) -> str:
        return event.url or f"{event.repository}:{event.number}:{event.subject_type}"

    opened_issues = {
        key(event): event for event in events if event.category == "opened_issues"
    }
    closed_issues = {
        key(event): event for event in events if event.category == "closed_issues"
    }
    opened_prs = {
        key(event): event for event in events if event.category == "opened_prs"
    }
    merged_prs = {
        key(event): event for event in events if event.category == "merged_prs"
    }
    closed_prs = {
        key(event): event for event in events if event.category == "closed_prs"
    }

    issue_durations = [
        (closed.occurred_at - opened_issues[item_key].occurred_at).days
        for item_key, closed in closed_issues.items()
        if item_key in opened_issues
    ]
    pr_durations = [
        (finished.occurred_at - opened_prs[item_key].occurred_at).days
        for collection in (merged_prs, closed_prs)
        for item_key, finished in collection.items()
        if item_key in opened_prs
    ]
    issues_open = max(0, len(opened_issues) - len(closed_issues))
    prs_open = max(0, len(opened_prs) - len(merged_prs) - len(closed_prs))
    return {
        "issues": {
            "opened": len(opened_issues),
            "closed": len(closed_issues),
            "open": issues_open,
            "median_days": round(median(issue_durations)) if issue_durations else None,
        },
        "prs": {
            "opened": len(opened_prs),
            "merged": len(merged_prs),
            "closed": len(closed_prs),
            "open": prs_open,
            "median_days": round(median(pr_durations)) if pr_durations else None,
        },
        "chart": {
            "labels": ["Issues", "Pull requests"],
            "datasets": [
                {
                    "label": "Reached closure",
                    "data": [len(closed_issues), 0],
                    "backgroundColor": "#22c55e",
                },
                {
                    "label": "Merged",
                    "data": [0, len(merged_prs)],
                    "backgroundColor": "#d946ef",
                },
                {
                    "label": "Closed another way",
                    "data": [0, len(closed_prs)],
                    "backgroundColor": "#ef4444",
                },
                {
                    "label": "Still in progress",
                    "data": [issues_open, prs_open],
                    "backgroundColor": "#94a3b8",
                },
            ],
        },
    }


def _repository_data(events: list[_ActivityEvent]) -> dict[str, Any]:
    totals: dict[str, int] = defaultdict(int)
    years: dict[str, set[int]] = defaultdict(set)
    categories: dict[str, set[str]] = defaultdict(set)
    yearly_repositories: dict[int, set[str]] = defaultdict(set)
    for event in events:
        totals[event.repository] += event.count
        years[event.repository].add(event.occurred_at.year)
        categories[event.repository].add(event.category)
        yearly_repositories[event.occurred_at.year].add(event.repository)

    top = sorted(totals, key=lambda repository: (-totals[repository], repository))[:12]
    stewardship = sorted(
        totals,
        key=lambda repository: (
            -len(years[repository]),
            -(
                max(years[repository]) - min(years[repository])
                if years[repository]
                else 0
            ),
            -totals[repository],
        ),
    )[:8]
    seen: set[str] = set()
    history = []
    for year in sorted(yearly_repositories):
        repositories = yearly_repositories[year]
        history.append(
            {
                "year": str(year),
                "new": len(repositories - seen),
                "returning": len(repositories & seen),
            }
        )
        seen.update(repositories)
    return {
        "count": len(totals),
        "organizations": len(
            {repository.split("/", 1)[0] for repository in totals if "/" in repository}
        ),
        "chart": {
            "labels": top,
            "data": [totals[repository] for repository in top],
        },
        "stewardship": [
            {
                "repository": repository,
                "active_years": len(years[repository]),
                "from": min(years[repository]),
                "to": max(years[repository]),
                "activity": totals[repository],
                "variety": len(categories[repository]),
                "url": f"https://github.com/{repository}",
            }
            for repository in stewardship
        ],
        "history": history,
    }


def _year_chapters(events: list[_ActivityEvent]) -> list[dict[str, Any]]:
    grouped: dict[int, list[_ActivityEvent]] = defaultdict(list)
    for event in events:
        grouped[event.occurred_at.year].append(event)
    chapters = []
    for year in sorted(grouped, reverse=True):
        items = grouped[year]
        repository_totals: dict[str, int] = defaultdict(int)
        for event in items:
            repository_totals[event.repository] += event.count
        top_repository = max(
            repository_totals, key=lambda repository: repository_totals[repository]
        )
        counts = {
            category: _count_events(items, category) for category in _CATEGORY_LABELS
        }
        chapters.append(
            {
                "year": year,
                "total": _count_events(items),
                "active_days": len({event.occurred_at.date() for event in items}),
                "repositories": len(repository_totals),
                "variety": sum(value > 0 for value in counts.values()),
                "top_repository": top_repository,
                "counts": counts,
            }
        )
    return chapters


def _dashboard_data(
    *,
    aggregated: dict[str, list[_Bucket]],
    events: list[_ActivityEvent],
    commits: list[_CommitSummary],
    user: str,
    scope: list[str],
) -> dict[str, Any]:
    sections = []
    for key, title in _SECTION_TITLES.items():
        buckets = aggregated.get(key, [])
        sections.append(
            {
                "id": key,
                "title": title,
                "labels": [bucket.label for bucket in buckets],
                "datasets": [
                    {
                        "label": label,
                        "data": [bucket.counts.get(category, 0) for bucket in buckets],
                        "backgroundColor": color,
                        "borderColor": color,
                        "borderWidth": 1,
                    }
                    for category, label, color in _CATEGORY_META
                ],
            }
        )

    years = aggregated.get("years", [])
    months = aggregated.get("months_last_12", [])
    totals = {
        category: _count_events(events, category) for category in _CATEGORY_LABELS
    }
    activity_dates = sorted({event.occurred_at.date() for event in events})
    active_months = {event.occurred_at.strftime("%Y-%m") for event in events}
    active_weeks = {event.occurred_at.strftime("%G-W%V") for event in events}
    repository_data = _repository_data(events)
    total = _count_events(events)

    def average_detail(category: str) -> str:
        recent = sum(bucket.counts.get(category, 0) for bucket in months)
        return (
            f"{totals[category] / max(1, len(years)):.1f}/year · "
            f"{recent / max(1, len(months)):.1f}/month recently"
        )

    summaries = [
        {
            "label": "Actions that added up",
            "value": total,
            "detail": (
                f"Since {activity_dates[0].isoformat()}"
                if activity_dates
                else "Your history starts here"
            ),
        },
        {
            "label": "Active days",
            "value": len(activity_dates),
            "detail": f"Across {len(active_weeks)} weeks and {len(active_months)} months",
        },
        {
            "label": "Repositories helped",
            "value": repository_data["count"],
            "detail": f"Across {repository_data['organizations']} owners or organizations",
        },
        {
            "label": "Issues started",
            "value": totals["opened_issues"],
            "detail": average_detail("opened_issues"),
        },
        {
            "label": "Issues brought to closure",
            "value": totals["closed_issues"],
            "detail": average_detail("closed_issues"),
        },
        {
            "label": "Pull requests proposed",
            "value": totals["opened_prs"],
            "detail": f"{totals['merged_prs']} reached merge",
        },
        {
            "label": "Conversations joined",
            "value": totals["comments"],
            "detail": average_detail("comments"),
        },
        {
            "label": "Commits contributed",
            "value": totals["commits"],
            "detail": average_detail("commits"),
        },
    ]

    gaps = [
        (later - earlier).days
        for earlier, later in zip(activity_dates, activity_dates[1:])
        if (later - earlier).days >= 30
    ]
    comments = [event for event in events if event.category == "comments"]
    conversations = {
        "issues": sum(
            event.count for event in comments if event.subject_type == "issue"
        ),
        "prs": sum(
            event.count for event in comments if event.subject_type == "pull_request"
        ),
        "others": sum(
            event.count
            for event in comments
            if event.subject_author is not None and event.subject_author != user
        ),
        "repositories": len({event.repository for event in comments}),
    }
    chapters = _year_chapters(events)
    records = []
    if chapters:
        most_active = max(chapters, key=lambda chapter: chapter["total"])
        broadest = max(chapters, key=lambda chapter: chapter["repositories"])
        most_varied = max(chapters, key=lambda chapter: chapter["variety"])
        records = [
            {
                "label": "Most active chapter",
                "value": str(most_active["year"]),
                "detail": f"{most_active['total']:,} recorded actions",
            },
            {
                "label": "Broadest chapter",
                "value": str(broadest["year"]),
                "detail": f"{broadest['repositories']} repositories",
            },
            {
                "label": "Most varied chapter",
                "value": str(most_varied["year"]),
                "detail": f"{most_varied['variety']} ways of contributing",
            },
        ]

    firsts = []
    for category, label, _ in _CATEGORY_META:
        matching = [event for event in events if event.category == category]
        if matching:
            firsts.append(
                {
                    "label": f"First {label.lower()}",
                    **_event_link(min(matching, key=lambda event: event.occurred_at)),
                }
            )

    today = datetime.now(timezone.utc).date()
    on_this_day = [
        _event_link(event)
        for event in sorted(events, key=lambda item: item.occurred_at, reverse=True)
        if event.occurred_at.date() < today
        and (event.occurred_at.month, event.occurred_at.day) == (today.month, today.day)
    ][:12]
    memories_by_url: dict[str, _ActivityEvent] = {}
    for event in sorted(events, key=lambda item: item.occurred_at):
        if event.url:
            memories_by_url.setdefault(event.url, event)
    memories = [_event_link(event) for event in list(memories_by_url.values())[:100]]

    rhythm = []
    for month_number in range(1, 13):
        rhythm.append(
            sum(
                event.count
                for event in events
                if event.occurred_at.month == month_number
            )
        )
    activity_days = aggregated.get("days_last_365", [])
    return {
        "user": user,
        "scope": scope,
        "hero": {
            "total": total,
            "first": activity_dates[0].isoformat() if activity_dates else None,
            "years": len({event.occurred_at.year for event in events}),
        },
        "summaries": summaries,
        "milestones": _milestones(events),
        "returns": {
            "count": len(gaps),
            "longest": max(gaps, default=0),
        },
        "conversations": conversations,
        "heatmap": [
            {"date": bucket.label, "count": sum(bucket.counts.values())}
            for bucket in activity_days
        ],
        "cumulative": _cumulative_data(events),
        "mix": {
            "labels": [label for _, label, _ in _CATEGORY_META],
            "data": [totals[category] for category, _, _ in _CATEGORY_META],
            "colors": [color for _, _, color in _CATEGORY_META],
        },
        "lifecycle": _lifecycle(events),
        "repositories": repository_data,
        "rhythm": rhythm,
        "records": records,
        "firsts": firsts,
        "on_this_day": on_this_day,
        "memories": memories,
        "chapters": chapters,
        "sections": sections,
        "commitAnalysis": _analyze_commits(commits),
    }


def _write_dashboard_html(
    *,
    aggregated: dict[str, list[_Bucket]],
    events: list[_ActivityEvent],
    commits: list[_CommitSummary],
    user: str,
    scope: list[str],
    path: Path,
) -> None:
    """Write an interactive HTML dashboard to a file.

    Args:
        aggregated: Activity data grouped into time buckets.
        events: Structured activity records used to derive personal insights.
        commits: Public default-branch commit summaries used for work-type analysis.
        user: GitHub username displayed in the report.
        scope: Repository scope labels displayed in the report.
        path: Destination HTML file.
    """
    data = _dashboard_data(
        aggregated=aggregated,
        events=events,
        commits=commits,
        user=user,
        scope=scope,
    )
    serialized = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    document = _HTML_TEMPLATE.replace("__DASHBOARD_DATA__", serialized)
    document = document.replace("__ESCAPED_USER__", html.escape(user))
    document = document.replace("__ESCAPED_SCOPE__", html.escape(", ".join(scope)))
    path.write_text(document, encoding="utf-8")


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Your GitHub story — __ESCAPED_USER__</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root { color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#f5f7fb; --panel:#fff; --text:#172033; --muted:#627087; --border:#dce3ed; --soft:#eef3f8; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); }
    main { max-width:1440px; margin:auto; padding:2rem; }
    header { padding:2.2rem; margin-bottom:1.5rem; border-radius:1rem; background:linear-gradient(135deg,#172554,#312e81 55%,#701a75); color:#fff; }
    header h1 { margin:0; font-size:clamp(2rem,5vw,3.4rem); }
    header .lead { max-width:760px; margin:.7rem 0 0; font-size:1.1rem; color:#dbeafe; }
    header .scope { margin:1rem 0 0; color:#cbd5e1; font-size:.85rem; }
    h2 { margin:0 0 .35rem; font-size:1.3rem; }
    h3 { margin:.15rem 0 .4rem; font-size:1rem; }
    p { line-height:1.55; }
    .intro { color:var(--muted); margin:.2rem 0 1rem; }
    .grid { display:grid; gap:1rem; }
    .summary-grid { grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin-bottom:1.5rem; }
    .two { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .three { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .panel,.card { background:var(--panel); border:1px solid var(--border); border-radius:.85rem; box-shadow:0 1px 3px #17203312; }
    .panel { padding:1.15rem; margin-bottom:1rem; }
    .card { padding:1rem; }
    .card strong { display:block; font-size:1.8rem; }
    .card small,.muted { color:var(--muted); }
    .chart { position:relative; height:340px; }
    .chart.tall { height:430px; }
    .pill-row { display:flex; flex-wrap:wrap; gap:.6rem; }
    .pill { padding:.55rem .75rem; background:var(--soft); border-radius:999px; font-size:.88rem; }
    #heatmap-wrap { overflow-x:auto; padding-bottom:.4rem; }
    #heatmap { display:grid; grid-auto-flow:column; grid-template-rows:repeat(7,12px); grid-auto-columns:12px; gap:3px; min-width:max-content; }
    .day { width:12px; height:12px; border-radius:2px; background:#e5e7eb; }
    .day[data-level="1"] { background:#9be9a8; } .day[data-level="2"] { background:#40c463; } .day[data-level="3"] { background:#30a14e; } .day[data-level="4"] { background:#216e39; }
    .day.blank { visibility:hidden; }
    .chapter-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:.8rem; max-height:700px; overflow:auto; }
    .chapter { padding:1rem; border:1px solid var(--border); border-radius:.7rem; }
    .chapter .year { font-size:1.4rem; font-weight:750; }
    .chapter .counts { margin-top:.6rem; color:var(--muted); font-size:.82rem; }
    .repo-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:.7rem; }
    .repo { padding:.8rem; border:1px solid var(--border); border-radius:.65rem; }
    a { color:#2563eb; text-decoration:none; } a:hover { text-decoration:underline; }
    #memory { min-height:115px; }
    button { appearance:none; border:0; border-radius:.55rem; background:#4f46e5; color:#fff; padding:.65rem .9rem; font-weight:650; cursor:pointer; }
    .detail-list { display:grid; gap:.55rem; }
    .detail { border-left:3px solid #818cf8; padding-left:.75rem; }
    .controls { display:flex; flex-wrap:wrap; gap:.6rem; align-items:center; margin:.75rem 0; }
    select,input[type="search"] { color:var(--text); background:var(--panel); border:1px solid var(--border); border-radius:.5rem; padding:.55rem .7rem; }
    .table-wrap { overflow:auto; }
    table { width:100%; border-collapse:collapse; font-size:.83rem; }
    th,td { padding:.5rem; border-bottom:1px solid var(--border); text-align:right; white-space:nowrap; }
    th:first-child,td:first-child { text-align:left; position:sticky; left:0; background:var(--panel); }
    .matrix-value { border-radius:.3rem; min-width:2.2rem; display:inline-block; padding:.25rem; text-align:center; }
    #commit-heatmap { display:grid; grid-auto-flow:column; grid-template-rows:repeat(7,12px); grid-auto-columns:12px; gap:3px; min-width:max-content; }
    .commit-list { display:grid; gap:.55rem; max-height:620px; overflow:auto; }
    .commit-item { padding:.7rem; border:1px solid var(--border); border-radius:.6rem; }
    .tag { display:inline-block; padding:.15rem .42rem; border-radius:999px; background:var(--soft); color:var(--muted); font-size:.75rem; margin-right:.3rem; }
    .subsection { margin-top:1.5rem; }
    footer { color:var(--muted); max-width:850px; margin:2rem auto 0; text-align:center; font-size:.9rem; }
    @media(max-width:850px) { main{padding:1rem}.two,.three{grid-template-columns:1fr}header{padding:1.5rem}.chart{height:300px} }
    @media(prefers-color-scheme:dark) { :root{--bg:#111827;--panel:#1f2937;--text:#f8fafc;--muted:#b4c0d3;--border:#374151;--soft:#273449}.day{background:#374151}a{color:#93c5fd} }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Your work adds up.</h1>
    <p class="lead" id="hero-copy">Each issue, proposal, comment, and commit is one part of a longer story.</p>
    <p class="scope">__ESCAPED_USER__ · __ESCAPED_SCOPE__</p>
  </header>

  <div id="summaries" class="grid summary-grid"></div>

  <section class="panel">
    <h2>The work never disappears</h2>
    <p class="intro">This view only moves forward. Quiet periods do not undo anything you already contributed.</p>
    <div class="chart tall"><canvas id="cumulative-chart"></canvas></div>
    <div id="milestones" class="pill-row"></div>
  </section>

  <section class="panel">
    <h2>Your activity tapestry</h2>
    <p class="intro">One square per day over the last year. Empty squares are simply days GitHub did not record these kinds of activity.</p>
    <div id="heatmap-wrap"><div id="heatmap" aria-label="Daily activity over the last year"></div></div>
  </section>

  <div class="grid three">
    <section class="panel"><h2>You kept coming back</h2><div id="returns"></div></section>
    <section class="panel"><h2>Conversations you joined</h2><div id="conversations"></div></section>
    <section class="panel"><h2>Personal highlights</h2><div id="records" class="detail-list"></div></section>
  </div>

  <div class="grid two">
    <section class="panel"><h2>Many ways of contributing</h2><p class="intro">Code is only one part of the work.</p><div class="chart"><canvas id="mix-chart"></canvas></div></section>
    <section class="panel"><h2>Things you carried forward</h2><p class="intro">Open items are ideas still in progress, not failures.</p><div class="chart"><canvas id="lifecycle-chart"></canvas></div><div id="lifecycle-copy"></div></section>
  </div>

  <div class="grid two">
    <section class="panel"><h2>Projects you helped</h2><p class="intro">Activity is not impact, but every project here holds part of your history.</p><div class="chart tall"><canvas id="repositories-chart"></canvas></div></section>
    <section class="panel"><h2>Exploration and return</h2><p class="intro">New projects show exploration; returning projects show care and continuity.</p><div class="chart tall"><canvas id="repository-history-chart"></canvas></div></section>
  </div>

  <section class="panel"><h2>Projects you kept returning to</h2><div id="stewardship" class="repo-list"></div></section>

  <section class="panel"><h2>Your natural rhythm</h2><p class="intro">A long-term rhythm, not a schedule you are expected to follow.</p><div class="chart"><canvas id="rhythm-chart"></canvas></div></section>

  <section class="panel"><h2>Your chapters</h2><p class="intro">Every year had its own shape. A smaller chapter is still part of the story.</p><div id="chapters" class="chapter-grid"></div></section>

  <div class="grid two">
    <section class="panel"><h2>First steps</h2><div id="firsts" class="detail-list"></div></section>
    <section class="panel"><h2>Rediscover something you did</h2><div id="memory"></div><button id="another-memory" type="button">Show me another</button></section>
  </div>

  <section class="panel" id="on-this-day-panel"><h2>On this day</h2><div id="on-this-day" class="detail-list"></div></section>

  <section id="commit-analysis" hidden>
    <section class="panel">
      <h2>What kinds of work did your commits hold?</h2>
      <p class="intro" id="commit-sample-copy"></p>
      <div class="grid three" id="commit-summary-cards"></div>
    </section>

    <div class="grid two">
      <section class="panel"><h2>Kinds of work</h2><p class="intro">Features are only one form of contribution.</p><div class="chart tall"><canvas id="commit-kinds-chart"></canvas></div></section>
      <section class="panel"><h2>A balanced body of work</h2><p class="intro">How many recognized kinds appeared in each represented year.</p><div class="chart tall"><canvas id="commit-variety-chart"></canvas></div></section>
    </div>

    <section class="panel"><h2>Work composition over time</h2><div class="controls"><button id="composition-mode" type="button">Show proportions</button></div><div class="chart tall"><canvas id="commit-composition-chart"></canvas></div></section>
    <section class="panel"><h2>Every kind of work accumulated</h2><p class="intro">These curves only move forward.</p><div class="chart tall"><canvas id="commit-cumulative-chart"></canvas></div><h3>Milestones</h3><div id="commit-milestones" class="pill-row"></div><h3 class="subsection">First recognized steps</h3><div id="commit-firsts" class="detail-list"></div></section>

    <section class="panel"><h2>Commit activity by kind</h2><div class="controls"><label for="commit-heatmap-category">Show</label><select id="commit-heatmap-category"><option value="all">All commit summaries</option></select></div><div id="heatmap-wrap"><div id="commit-heatmap"></div></div></section>

    <section class="panel"><h2>Repository × work-type map</h2><p class="intro">Different projects asked different things of you.</p><div class="table-wrap"><table id="commit-matrix"></table></div></section>
    <section class="panel"><h2>Roles you played in different projects</h2><div id="commit-roles" class="repo-list"></div></section>

    <section class="panel"><h2>Recurring themes</h2><p class="intro">Common words from the descriptive part of classified summaries.</p><div class="chart tall"><canvas id="commit-topics-chart"></canvas></div></section>

    <section class="panel"><h2>Feature and stabilization rhythm</h2><p class="intro">New work is often accompanied by fixes, tests, documentation, and maintenance.</p><div class="chart tall"><canvas id="commit-rhythm-chart"></canvas></div></section>
    <section class="panel"><h2>Maintenance seasons</h2><p class="intro">Periods where sustaining, explaining, testing, and improving existing work took the foreground.</p><div id="commit-seasons" class="repo-list"></div></section>
    <section class="panel"><h2>What these summaries remember</h2><div id="commit-insights" class="detail-list"></div></section>

    <section class="panel">
      <h2>Commit-summary gallery</h2>
      <div class="controls"><select id="commit-gallery-category"><option value="all">Every kind</option></select><input id="commit-gallery-search" type="search" placeholder="Search summaries or repositories"><span id="commit-gallery-count" class="muted"></span></div>
      <div id="commit-gallery" class="commit-list"></div>
    </section>
  </section>

  <div id="period-charts" class="grid two"></div>

  <footer>GitHub records only one narrow slice of a life. These numbers cannot measure your worth, happiness, care, learning, rest, or the importance of work that happened elsewhere.</footer>
</main>
<script>
  const dashboard = __DASHBOARD_DATA__;
  const isDark = matchMedia('(prefers-color-scheme: dark)').matches;
  const foreground = isDark ? '#f8fafc' : '#172033';
  const grid = isDark ? '#374151' : '#dce3ed';
  const number = value => Number(value || 0).toLocaleString();
  const el = (tag, className, text) => { const node=document.createElement(tag); if(className)node.className=className; if(text!==undefined)node.textContent=text; return node; };
  const link = item => { const a=el('a'); a.textContent=item.title; if(item.url?.startsWith('https://github.com/')){a.href=item.url;a.target='_blank';a.rel='noreferrer';} return a; };

  if (dashboard.hero.first) document.querySelector('#hero-copy').textContent = `${number(dashboard.hero.total)} recorded actions across ${number(dashboard.hero.years)} years, beginning ${dashboard.hero.first}. Each one is a real part of your history.`;
  for (const summary of dashboard.summaries) { const card=el('div','card'); card.append(el('div','',summary.label),el('strong','',number(summary.value)),el('small','',summary.detail)); document.querySelector('#summaries').append(card); }

  Chart.defaults.color=foreground; Chart.defaults.borderColor=grid;
  new Chart(document.querySelector('#cumulative-chart'), {type:'line',data:dashboard.cumulative,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom'}},scales:{x:{grid:{color:grid},ticks:{maxTicksLimit:14}},y:{beginAtZero:true,grid:{color:grid}}}}});
  for (const milestone of dashboard.milestones) document.querySelector('#milestones').append(el('span','pill',`${number(milestone.value)} actions · ${milestone.date}`));

  const heatmap=document.querySelector('#heatmap'); const positives=dashboard.heatmap.map(day=>day.count).filter(Boolean).sort((a,b)=>a-b); const thresholds=[.25,.5,.75].map(q=>positives[Math.floor((positives.length-1)*q)]||1);
  if(dashboard.heatmap.length){const first=new Date(`${dashboard.heatmap[0].date}T00:00:00Z`).getUTCDay();for(let i=0;i<(first+6)%7;i++)heatmap.append(el('div','day blank'));}
  for(const day of dashboard.heatmap){const square=el('div','day');square.dataset.level=day.count===0?0:day.count<=thresholds[0]?1:day.count<=thresholds[1]?2:day.count<=thresholds[2]?3:4;square.title=`${day.date}: ${number(day.count)} recorded actions`;heatmap.append(square);}

  const returns=dashboard.returns; document.querySelector('#returns').append(el('strong','',number(returns.count)),el('p','muted',returns.count?`times you returned after 30 or more quiet days. Your longest pause before returning was ${number(returns.longest)} days.`:'Your story does not need a streak to be meaningful.'));
  const conversations=dashboard.conversations; document.querySelector('#conversations').append(el('strong','',number(conversations.issues+conversations.prs)),el('p','muted',`${number(conversations.issues)} issue comments and ${number(conversations.prs)} pull-request comments across ${number(conversations.repositories)} repositories.${conversations.others?` ${number(conversations.others)} were on work started by someone else.`:''}`));
  for(const record of dashboard.records){const item=el('div','detail');item.append(el('strong','',record.value),el('small','',`${record.label} · ${record.detail}`));document.querySelector('#records').append(item);}

  new Chart(document.querySelector('#mix-chart'),{type:'doughnut',data:{labels:dashboard.mix.labels,datasets:[{data:dashboard.mix.data,backgroundColor:dashboard.mix.colors}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}}}});
  new Chart(document.querySelector('#lifecycle-chart'),{type:'bar',data:dashboard.lifecycle.chart,options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,grid:{color:grid}},y:{stacked:true,beginAtZero:true,grid:{color:grid}}}}});
  const life=dashboard.lifecycle; const issueDuration=life.issues.median_days===null?'':` Median time to closure: ${number(life.issues.median_days)} days.`; const prDuration=life.prs.median_days===null?'':` Median time to an outcome: ${number(life.prs.median_days)} days.`; document.querySelector('#lifecycle-copy').append(el('p','muted',`${number(life.issues.closed)} of ${number(life.issues.opened)} authored issues reached closure.${issueDuration}`),el('p','muted',`${number(life.prs.merged)} of ${number(life.prs.opened)} proposed pull requests reached merge.${prDuration}`));

  new Chart(document.querySelector('#repositories-chart'),{type:'bar',data:{labels:dashboard.repositories.chart.labels,datasets:[{label:'Recorded actions',data:dashboard.repositories.chart.data,backgroundColor:'#6366f1'}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,grid:{color:grid}},y:{grid:{display:false}}}}});
  const repoHistory=dashboard.repositories.history; new Chart(document.querySelector('#repository-history-chart'),{type:'bar',data:{labels:repoHistory.map(item=>item.year),datasets:[{label:'New projects',data:repoHistory.map(item=>item.new),backgroundColor:'#06b6d4'},{label:'Returning projects',data:repoHistory.map(item=>item.returning),backgroundColor:'#8b5cf6'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,grid:{color:grid}},y:{stacked:true,beginAtZero:true,grid:{color:grid}}}}});
  for(const repo of dashboard.repositories.stewardship){const item=el('div','repo');const a=el('a');a.href=repo.url;a.target='_blank';a.rel='noreferrer';a.textContent=repo.repository;item.append(a,el('div','muted',`${repo.active_years} active years · ${repo.from}–${repo.to} · ${number(repo.activity)} actions`));document.querySelector('#stewardship').append(item);}

  new Chart(document.querySelector('#rhythm-chart'),{type:'bar',data:{labels:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],datasets:[{label:'All-time recorded actions',data:dashboard.rhythm,backgroundColor:'#0ea5e9'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,grid:{color:grid}}}}});
  for(const chapter of dashboard.chapters){const card=el('article','chapter');card.append(el('div','year',String(chapter.year)),el('strong','',`${number(chapter.total)} actions`),el('div','muted',`${number(chapter.active_days)} active days · ${number(chapter.repositories)} repositories`),el('div','counts',`Most visited: ${chapter.top_repository}`));document.querySelector('#chapters').append(card);}

  const addLinkedDetail=(root,item,prefix='')=>{const node=el('div','detail');node.append(el('small','',`${prefix}${item.date} · ${item.action}`),document.createElement('br'),link(item),el('small','',` · ${item.repository}`));root.append(node);};
  for(const item of dashboard.firsts)addLinkedDetail(document.querySelector('#firsts'),item);
  if(!dashboard.on_this_day.length)document.querySelector('#on-this-day-panel').hidden=true;else for(const item of dashboard.on_this_day)addLinkedDetail(document.querySelector('#on-this-day'),item);
  let memoryIndex=-1; const showMemory=()=>{const root=document.querySelector('#memory');root.replaceChildren();if(!dashboard.memories.length){root.append(el('p','muted','Your future memories will appear here.'));return;}let next=memoryIndex;while(next===memoryIndex&&dashboard.memories.length>1)next=Math.floor(Math.random()*dashboard.memories.length);memoryIndex=next;addLinkedDetail(root,dashboard.memories[memoryIndex],'From ');}; document.querySelector('#another-memory').addEventListener('click',showMemory);showMemory();

  const commits=dashboard.commitAnalysis;
  if(commits.available){
    document.querySelector('#commit-analysis').hidden=false;
    const localSource=commits.sample.localRepositories?`${number(commits.sample.localRepositories)} local histories${commits.sample.shallowRepositories?` (${number(commits.sample.shallowRepositories)} shallow)`:''}`:'';
    const githubSource=commits.sample.githubRepositories?`${number(commits.sample.githubRepositories)} bounded GitHub samples`:'';
    const commitSources=[localSource,githubSource].filter(Boolean).join(' and ');
    document.querySelector('#commit-sample-copy').textContent=`${number(commits.sample.commits)} public default-branch commit summaries across ${number(commits.sample.repositories)} repositories, from ${commits.sample.from} to ${commits.sample.to}${commitSources?`, using ${commitSources}`:''}. Local histories reflect the clones on disk and include up to 2,000 matching commits per repository; GitHub histories are deliberately bounded. “Other” is a normal category, not a mistake.`;
    const commitCards=[
      ['Summaries considered',commits.sample.commits,`${commits.sample.repositories} public repositories`],
      ['Care and stewardship',`${commits.care.share}%`,`${number(commits.care.count)} commits across ${commits.care.categories} sustaining kinds`],
      ['Recognized prefixes',`${commits.coverage.percent}%`,`${number(commits.coverage.classified)} of ${number(commits.coverage.total)} summaries`],
    ];
    for(const [label,value,detail] of commitCards){const card=el('div','card');card.append(el('div','',label),el('strong','',String(value)),el('small','',detail));document.querySelector('#commit-summary-cards').append(card);}

    new Chart(document.querySelector('#commit-kinds-chart'),{type:'bar',data:{labels:commits.kinds.labels,datasets:[{label:'Commits',data:commits.kinds.data,backgroundColor:commits.kinds.colors}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,grid:{color:grid}},y:{grid:{display:false}}}}});
    new Chart(document.querySelector('#commit-variety-chart'),{type:'bar',data:{labels:commits.variety.labels,datasets:[{label:'Kinds of work',data:commits.variety.data,backgroundColor:'#8b5cf6'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0},grid:{color:grid}}}}});

    const absoluteComposition=commits.composition.datasets.map(dataset=>dataset.data.slice());
    const compositionChart=new Chart(document.querySelector('#commit-composition-chart'),{type:'bar',data:commits.composition,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,grid:{color:grid}},y:{stacked:true,beginAtZero:true,grid:{color:grid}}}}});
    let proportional=false;document.querySelector('#composition-mode').addEventListener('click',event=>{proportional=!proportional;for(let point=0;point<commits.composition.labels.length;point++){const total=absoluteComposition.reduce((sum,data)=>sum+data[point],0);for(let dataset=0;dataset<compositionChart.data.datasets.length;dataset++)compositionChart.data.datasets[dataset].data[point]=proportional?(total?Math.round(absoluteComposition[dataset][point]/total*1000)/10:0):absoluteComposition[dataset][point];}compositionChart.options.scales.y.max=proportional?100:undefined;compositionChart.options.scales.y.ticks.callback=proportional?value=>`${value}%`:undefined;event.currentTarget.textContent=proportional?'Show totals':'Show proportions';compositionChart.update();});
    new Chart(document.querySelector('#commit-cumulative-chart'),{type:'line',data:commits.cumulative,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom'}},scales:{x:{grid:{color:grid},ticks:{maxTicksLimit:14}},y:{beginAtZero:true,grid:{color:grid}}}}});
    for(const milestone of commits.milestones){const a=el('a','pill',`${number(milestone.value)} ${milestone.category.toLowerCase()} · ${milestone.date}`);if(milestone.url?.startsWith('https://github.com/')){a.href=milestone.url;a.target='_blank';a.rel='noreferrer';}document.querySelector('#commit-milestones').append(a);}
    for(const first of commits.firsts){const item=el('div','detail');const a=el('a','',first.headline);if(first.url?.startsWith('https://github.com/')){a.href=first.url;a.target='_blank';a.rel='noreferrer';}item.append(el('small','',`First recognized ${first.category.toLowerCase()} · ${first.date} · ${first.repository}`),document.createElement('br'),a);document.querySelector('#commit-firsts').append(item);}

    const heatmapSelect=document.querySelector('#commit-heatmap-category');const gallerySelect=document.querySelector('#commit-gallery-category');for(const category of commits.categories){for(const select of [heatmapSelect,gallerySelect]){const option=el('option','',category.label);option.value=category.id;select.append(option);}}
    const commitDays=new Map(commits.days.map(day=>[day.date,day]));
    const renderCommitHeatmap=()=>{const root=document.querySelector('#commit-heatmap');root.replaceChildren();const category=heatmapSelect.value;const end=new Date(`${commits.sample.to}T00:00:00Z`);const days=[];for(let offset=364;offset>=0;offset--){const current=new Date(end);current.setUTCDate(end.getUTCDate()-offset);const date=current.toISOString().slice(0,10);const record=commitDays.get(date);days.push({date,count:record?(category==='all'?record.total:(record.counts[category]||0)):0});}const first=new Date(`${days[0].date}T00:00:00Z`).getUTCDay();for(let index=0;index<(first+6)%7;index++)root.append(el('div','day blank'));const positives=days.map(day=>day.count).filter(Boolean).sort((a,b)=>a-b);const thresholds=[.25,.5,.75].map(q=>positives[Math.floor((positives.length-1)*q)]||1);for(const day of days){const square=el('div','day');square.dataset.level=day.count===0?0:day.count<=thresholds[0]?1:day.count<=thresholds[1]?2:day.count<=thresholds[2]?3:4;square.title=`${day.date}: ${number(day.count)} matching commits`;root.append(square);}};heatmapSelect.addEventListener('change',renderCommitHeatmap);renderCommitHeatmap();

    const matrix=document.querySelector('#commit-matrix');const head=el('thead');const headRow=el('tr');headRow.append(el('th','','Repository'));for(const category of commits.matrix.categories)headRow.append(el('th','',category.label));head.append(headRow);matrix.append(head);const body=el('tbody');const matrixMaximum=Math.max(1,...Object.values(commits.matrix.values).flatMap(values=>Object.values(values)));for(const repository of commits.matrix.repositories){const row=el('tr');row.append(el('td','',repository));for(const category of commits.matrix.categories){const value=commits.matrix.values[repository][category.id]||0;const cell=el('td');const span=el('span','matrix-value',number(value));span.style.background=`rgba(99,102,241,${value?0.12+value/matrixMaximum*0.72:0})`;cell.append(span);row.append(cell);}body.append(row);}matrix.append(body);
    for(const role of commits.roles){const card=el('div','repo');const a=el('a','',role.repository);a.href=role.url;a.target='_blank';a.rel='noreferrer';card.append(a,el('div','muted',`${role.primary} was the leading kind · ${number(role.total)} commit summaries · ${role.variety} kinds`));const tags=el('div');for(const detail of role.details)tags.append(el('span','tag',`${detail.label}: ${number(detail.count)}`));card.append(tags);document.querySelector('#commit-roles').append(card);}

    new Chart(document.querySelector('#commit-topics-chart'),{type:'bar',data:{labels:commits.topics.labels,datasets:[{label:'Mentions',data:commits.topics.data,backgroundColor:'#0ea5e9'}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,grid:{color:grid}},y:{grid:{display:false}}}}});
    new Chart(document.querySelector('#commit-rhythm-chart'),{type:'bar',data:commits.rhythm,options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,grid:{color:grid},ticks:{maxTicksLimit:12}},y:{stacked:true,beginAtZero:true,grid:{color:grid}}}}});
    for(const season of commits.seasons){const card=el('div','repo');card.append(el('strong','',String(season.year)),el('div','muted',`${number(season.care)} care-and-stewardship commits · ${season.share}% of the represented year · led by ${season.leading}`));document.querySelector('#commit-seasons').append(card);}
    for(const insight of commits.insights)document.querySelector('#commit-insights').append(el('div','detail',insight));

    const renderGallery=()=>{const root=document.querySelector('#commit-gallery');root.replaceChildren();const category=gallerySelect.value;const query=document.querySelector('#commit-gallery-search').value.trim().toLowerCase();const matching=commits.gallery.filter(item=>(category==='all'||item.category===category)&&(!query||`${item.headline} ${item.repository} ${item.scope||''}`.toLowerCase().includes(query)));document.querySelector('#commit-gallery-count').textContent=`${number(matching.length)} matching summaries`;for(const item of matching.slice(0,100)){const card=el('div','commit-item');const a=el('a','',item.headline);if(item.url?.startsWith('https://github.com/')){a.href=item.url;a.target='_blank';a.rel='noreferrer';}const metadata=el('div','muted',`${item.date} · ${item.repository}`);const tags=el('div');tags.append(el('span','tag',item.categoryLabel));if(item.scope)tags.append(el('span','tag',item.scope));card.append(a,metadata,tags);root.append(card);}};gallerySelect.addEventListener('change',renderGallery);document.querySelector('#commit-gallery-search').addEventListener('input',renderGallery);renderGallery();
  }

  for(const section of dashboard.sections){const panel=el('section','panel');panel.append(el('h2','',section.title));const wrap=el('div','chart');const canvas=el('canvas');wrap.append(canvas);panel.append(wrap);document.querySelector('#period-charts').append(panel);new Chart(canvas,{type:'bar',data:{labels:section.labels,datasets:section.datasets},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,beginAtZero:true,grid:{color:grid}},y:{stacked:true,grid:{color:grid},ticks:{autoSkip:false}}}}});}
</script>
</body>
</html>
"""

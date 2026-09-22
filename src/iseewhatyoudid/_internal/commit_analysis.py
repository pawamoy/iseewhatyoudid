from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from iseewhatyoudid._internal.activity import (
    _CommitSummary,
    _is_default_merge_commit,
)

_CATEGORY_META: tuple[tuple[str, str, str], ...] = (
    ("features", "Features", "#8b5cf6"),
    ("fixes", "Bug fixes", "#ef4444"),
    ("documentation", "Documentation", "#06b6d4"),
    ("tests", "Tests", "#22c55e"),
    ("refactoring", "Refactoring", "#f59e0b"),
    ("performance", "Performance", "#14b8a6"),
    ("security", "Security", "#dc2626"),
    ("accessibility", "Accessibility", "#0ea5e9"),
    ("localization", "Localization", "#a855f7"),
    ("dependencies", "Dependencies", "#64748b"),
    ("ci", "CI/CD", "#6366f1"),
    ("build", "Build and releases", "#78716c"),
    ("maintenance", "Maintenance", "#84cc16"),
    ("style", "Style and formatting", "#ec4899"),
    ("reverts", "Reverts", "#f97316"),
    ("other", "Other", "#94a3b8"),
)
_LABELS = {category: label for category, label, _ in _CATEGORY_META}
_COLORS = {category: color for category, _, color in _CATEGORY_META}
_ALIASES = {
    "feat": "features",
    "feature": "features",
    "features": "features",
    "enh": "features",
    "enhancement": "features",
    "fix": "fixes",
    "bugfix": "fixes",
    "hotfix": "fixes",
    "docs": "documentation",
    "doc": "documentation",
    "documentation": "documentation",
    "test": "tests",
    "tests": "tests",
    "testing": "tests",
    "refactor": "refactoring",
    "refactoring": "refactoring",
    "cleanup": "refactoring",
    "perf": "performance",
    "performance": "performance",
    "optimize": "performance",
    "security": "security",
    "sec": "security",
    "a11y": "accessibility",
    "accessibility": "accessibility",
    "i18n": "localization",
    "l10n": "localization",
    "translation": "localization",
    "translations": "localization",
    "deps": "dependencies",
    "dep": "dependencies",
    "dependencies": "dependencies",
    "dependabot": "dependencies",
    "ci": "ci",
    "cd": "ci",
    "actions": "ci",
    "build": "build",
    "packaging": "build",
    "release": "build",
    "chore": "maintenance",
    "maint": "maintenance",
    "maintenance": "maintenance",
    "style": "style",
    "format": "style",
    "lint": "style",
    "revert": "reverts",
}
_CARE_CATEGORIES = {
    "documentation",
    "tests",
    "refactoring",
    "performance",
    "security",
    "accessibility",
    "localization",
    "dependencies",
    "ci",
    "build",
    "maintenance",
    "style",
}
_PREFIX = re.compile(
    r"^\s*(?P<type>[A-Za-z][\w-]*)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?\s*:\s*(?P<description>.+)$"
)
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")
_STOP_WORDS = {
    "add",
    "adds",
    "added",
    "allow",
    "and",
    "are",
    "change",
    "changes",
    "for",
    "from",
    "into",
    "make",
    "more",
    "not",
    "remove",
    "support",
    "that",
    "the",
    "this",
    "update",
    "updates",
    "use",
    "using",
    "with",
}


@dataclass(frozen=True)
class _ClassifiedCommit:
    commit: _CommitSummary
    category: str
    scope: str | None
    description: str
    recognized: bool


def _classify_commit(commit: _CommitSummary) -> _ClassifiedCommit:
    match = _PREFIX.match(commit.headline)
    if not match:
        return _ClassifiedCommit(
            commit=commit,
            category="other",
            scope=None,
            description=commit.headline,
            recognized=False,
        )
    raw_type = match.group("type").lower()
    category = _ALIASES.get(raw_type, "other")
    scope = match.group("scope")
    return _ClassifiedCommit(
        commit=commit,
        category=category,
        scope=scope.strip().lower()[:80] if scope else None,
        description=match.group("description").strip(),
        recognized=raw_type in _ALIASES,
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


def _datasets(
    categories: list[str], values: dict[str, list[int]], *, lines: bool = False
) -> list[dict[str, Any]]:
    return [
        {
            "label": _LABELS[category],
            "data": values[category],
            "backgroundColor": (
                f"{_COLORS[category]}28" if lines else _COLORS[category]
            ),
            "borderColor": _COLORS[category],
            "borderWidth": 2 if lines else 1,
            "pointRadius": 0 if lines else None,
            "tension": 0.2 if lines else None,
            "fill": False if lines else None,
        }
        for category in categories
    ]


def _analyze_commits(commits: list[_CommitSummary]) -> dict[str, Any]:
    classified = sorted(
        (
            _classify_commit(commit)
            for commit in commits
            if not _is_default_merge_commit(commit)
        ),
        key=lambda item: item.commit.committed_at,
    )
    if not classified:
        return {"available": False}

    counts = Counter(item.category for item in classified)
    active_categories = [
        category for category, _, _ in _CATEGORY_META if counts[category]
    ]
    top_categories = sorted(
        active_categories, key=lambda category: (-counts[category], category)
    )[:8]
    years = sorted({item.commit.committed_at.year for item in classified})
    by_year: dict[int, Counter[str]] = defaultdict(Counter)
    by_repository: dict[str, Counter[str]] = defaultdict(Counter)
    by_month: dict[str, Counter[str]] = defaultdict(Counter)
    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    topics: Counter[str] = Counter()
    for item in classified:
        commit = item.commit
        by_year[commit.committed_at.year][item.category] += 1
        by_repository[commit.repository][item.category] += 1
        by_month[commit.committed_at.strftime("%Y-%m")][item.category] += 1
        by_day[commit.committed_at.date().isoformat()][item.category] += 1
        for word in _WORDS.findall(item.description.lower()):
            if len(word) > 2 and word not in _STOP_WORDS and not word.isdigit():
                topics[word] += 1

    composition_values = {
        category: [by_year[year][category] for year in years]
        for category in top_categories
    }
    first_month = classified[0].commit.committed_at.date().replace(day=1)
    last_month = classified[-1].commit.committed_at.date().replace(day=1)
    months = _month_range(first_month, last_month)
    running = Counter()
    cumulative_values = {category: [] for category in top_categories}
    for month in months:
        running.update(by_month[month])
        for category in top_categories:
            cumulative_values[category].append(running[category])

    repositories = sorted(
        by_repository,
        key=lambda repository: (-sum(by_repository[repository].values()), repository),
    )
    local_repositories = {
        item.commit.repository for item in classified if item.commit.source == "local"
    }
    shallow_repositories = {
        item.commit.repository
        for item in classified
        if item.commit.source == "local" and not item.commit.history_complete
    }
    github_repositories = {
        item.commit.repository for item in classified if item.commit.source == "github"
    }
    matrix_repositories = repositories[:12]
    matrix_categories = top_categories[:8]
    roles = []
    for repository in repositories[:12]:
        repository_counts = by_repository[repository]
        primary = max(
            repository_counts,
            key=lambda category: repository_counts[category],
        )
        roles.append(
            {
                "repository": repository,
                "total": sum(repository_counts.values()),
                "primary": _LABELS[primary],
                "variety": len(repository_counts),
                "details": [
                    {"label": _LABELS[category], "count": count}
                    for category, count in repository_counts.most_common(4)
                ],
                "url": f"https://github.com/{repository}",
            }
        )

    variety = [len(by_year[year]) for year in years]
    milestones = []
    category_running: Counter[str] = Counter()
    thresholds = {10, 25, 50, 100, 250, 500, 1_000}
    for item in classified:
        category_running[item.category] += 1
        value = category_running[item.category]
        if value in thresholds:
            milestones.append(
                {
                    "category": _LABELS[item.category],
                    "value": value,
                    "date": item.commit.committed_at.date().isoformat(),
                    "headline": item.commit.headline,
                    "url": item.commit.url,
                }
            )

    care_count = sum(counts[category] for category in _CARE_CATEGORIES)
    latest_months = months[-36:]
    rhythm_groups = {
        "Features": {"features"},
        "Fixes": {"fixes"},
        "Tests": {"tests"},
        "Documentation": {"documentation"},
        "Care and maintenance": _CARE_CATEGORIES - {"tests", "documentation"},
        "Other": {"other", "reverts"},
    }
    rhythm_colors = ("#8b5cf6", "#ef4444", "#22c55e", "#06b6d4", "#f59e0b", "#94a3b8")
    rhythm_datasets = []
    for (label, categories), color in zip(rhythm_groups.items(), rhythm_colors):
        rhythm_datasets.append(
            {
                "label": label,
                "data": [
                    sum(by_month[month][category] for category in categories)
                    for month in latest_months
                ],
                "backgroundColor": color,
            }
        )

    seasons = []
    for year in years:
        total = sum(by_year[year].values())
        care = sum(by_year[year][category] for category in _CARE_CATEGORIES)
        if care:
            seasons.append(
                {
                    "year": year,
                    "care": care,
                    "total": total,
                    "share": round(care / total * 100),
                    "leading": _LABELS[
                        max(
                            _CARE_CATEGORIES,
                            key=lambda category: by_year[year][category],
                        )
                    ],
                }
            )
    seasons.sort(key=lambda item: (-item["share"], -item["care"]))

    insights = []
    docs_repositories = sum(
        by_repository[repository]["documentation"] > 0 for repository in repositories
    )
    test_months = sum(by_month[month]["tests"] > 0 for month in months)
    fix_repositories = sum(
        by_repository[repository]["fixes"] > 0 for repository in repositories
    )
    if docs_repositories:
        insights.append(f"You documented {docs_repositories} public repositories.")
    if test_months:
        insights.append(f"Testing work appeared across {test_months} different months.")
    care_years = sum(
        any(by_year[year][category] for category in _CARE_CATEGORIES) for year in years
    )
    if care_years:
        insights.append(
            f"Care and maintenance appeared in {care_years} of {len(years)} represented years."
        )
    widest_repository = max(repositories, key=lambda repo: len(by_repository[repo]))
    insights.append(
        f"{widest_repository} contains your widest recorded variety: "
        f"{len(by_repository[widest_repository])} kinds of work."
    )
    security_items = [item for item in classified if item.category == "security"]
    if security_items:
        insights.append(
            "Your first recognized security change among these summaries was "
            f"{security_items[0].commit.committed_at.date().isoformat()}."
        )
    docs_and_tests = counts["documentation"] + counts["tests"]
    if docs_and_tests:
        insights.append(
            f"Tests and documentation account for {docs_and_tests} recorded changes."
        )
    if fix_repositories:
        insights.append(f"You recorded fixes across {fix_repositories} repositories.")
    if len(years) > 1:
        first_variety = len(by_year[years[0]])
        latest_variety = len(by_year[years[-1]])
        if latest_variety >= first_variety:
            insights.append(
                f"Your recorded work expanded from {first_variety} kinds in "
                f"{years[0]} to {latest_variety} in {years[-1]}."
            )
        else:
            insights.append(
                f"These summaries hold {first_variety} kinds of work in {years[0]} "
                f"and {latest_variety} in {years[-1]}."
            )
    quietest_year = min(years, key=lambda year: sum(by_year[year].values()))
    insights.append(
        f"Even the smallest recorded chapter, {quietest_year}, contained "
        f"{len(by_year[quietest_year])} kinds of work."
    )

    gallery = [
        {
            "oid": item.commit.oid,
            "headline": item.commit.headline,
            "description": item.description,
            "category": item.category,
            "categoryLabel": _LABELS[item.category],
            "scope": item.scope,
            "date": item.commit.committed_at.date().isoformat(),
            "repository": item.commit.repository,
            "url": item.commit.url,
        }
        for item in reversed(classified)
    ]
    firsts = []
    for category in active_categories:
        item = next(item for item in classified if item.category == category)
        firsts.append(
            {
                "category": _LABELS[category],
                "date": item.commit.committed_at.date().isoformat(),
                "headline": item.commit.headline,
                "repository": item.commit.repository,
                "url": item.commit.url,
            }
        )
    return {
        "available": True,
        "sample": {
            "commits": len(classified),
            "repositories": len(repositories),
            "localRepositories": len(local_repositories),
            "shallowRepositories": len(shallow_repositories),
            "githubRepositories": len(github_repositories),
            "from": classified[0].commit.committed_at.date().isoformat(),
            "to": classified[-1].commit.committed_at.date().isoformat(),
        },
        "kinds": {
            "labels": [_LABELS[category] for category in active_categories],
            "data": [counts[category] for category in active_categories],
            "colors": [_COLORS[category] for category in active_categories],
        },
        "composition": {
            "labels": [str(year) for year in years],
            "datasets": _datasets(top_categories, composition_values),
        },
        "cumulative": {
            "labels": months,
            "datasets": _datasets(top_categories, cumulative_values, lines=True),
        },
        "days": [
            {
                "date": day,
                "counts": dict(day_counts),
                "total": sum(day_counts.values()),
            }
            for day, day_counts in sorted(by_day.items())
        ],
        "categories": [
            {"id": category, "label": _LABELS[category], "color": _COLORS[category]}
            for category in active_categories
        ],
        "matrix": {
            "repositories": matrix_repositories,
            "categories": [
                {"id": category, "label": _LABELS[category]}
                for category in matrix_categories
            ],
            "values": {
                repository: {
                    category: by_repository[repository][category]
                    for category in matrix_categories
                }
                for repository in matrix_repositories
            },
        },
        "roles": roles,
        "variety": {"labels": [str(year) for year in years], "data": variety},
        "milestones": milestones[-24:],
        "firsts": firsts,
        "care": {
            "count": care_count,
            "share": round(care_count / len(classified) * 100),
            "categories": len(
                [category for category in _CARE_CATEGORIES if counts[category]]
            ),
        },
        "rhythm": {"labels": latest_months, "datasets": rhythm_datasets},
        "seasons": seasons[:6],
        "gallery": gallery,
        "topics": {
            "labels": [word for word, _ in topics.most_common(20)],
            "data": [count for _, count in topics.most_common(20)],
        },
        "coverage": {
            "classified": sum(item.recognized for item in classified),
            "total": len(classified),
            "percent": round(
                sum(item.recognized for item in classified) / len(classified) * 100
            ),
        },
        "insights": insights,
    }

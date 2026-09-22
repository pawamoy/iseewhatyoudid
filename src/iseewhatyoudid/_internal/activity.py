from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

_CATEGORIES: tuple[str, ...] = (
    "opened_issues",
    "closed_issues",
    "opened_prs",
    "merged_prs",
    "closed_prs",
    "comments",
    "commits",
)
_DEFAULT_MERGE_SUBJECT = re.compile(
    r"^Merge (?:branch(?:es)?|remote-tracking branch|tag|commit|pull request)\b"
)


@dataclass
class _Bucket:
    label: str
    counts: dict[str, int]


@dataclass(frozen=True)
class _ActivityEvent:
    category: str
    occurred_at: datetime
    repository: str
    count: int = 1
    title: str | None = None
    url: str | None = None
    number: int | None = None
    subject_type: str | None = None
    subject_author: str | None = None


@dataclass(frozen=True)
class _CommitSummary:
    oid: str
    headline: str
    committed_at: datetime
    repository: str
    url: str
    source: str = "github"
    history_complete: bool = False
    is_merge: bool | None = None


@dataclass
class _CollectedActivity:
    events: list[_ActivityEvent]
    commits: list[_CommitSummary]


def _is_default_merge_commit(commit: _CommitSummary) -> bool:
    return commit.is_merge is not False and bool(
        _DEFAULT_MERGE_SUBJECT.match(commit.headline)
    )


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _shift_month(month: date, offset: int) -> date:
    year = month.year + (month.month - 1 + offset) // 12
    month_number = (month.month - 1 + offset) % 12 + 1
    return date(year, month_number, 1)


def _build_year_buckets(values: list[datetime], *, now: datetime) -> list[_Bucket]:
    if values:
        min_year = min(value.astimezone(timezone.utc).year for value in values)
    else:
        min_year = now.year
    buckets = []
    for year in range(min_year, now.year + 1):
        buckets.append(
            _Bucket(label=str(year), counts={category: 0 for category in _CATEGORIES})
        )
    return buckets


def _build_month_buckets(*, now: datetime) -> list[_Bucket]:
    this_month = _month_start(now.date())
    buckets = []
    for offset in range(-11, 1):
        bucket_month = _shift_month(this_month, offset)
        buckets.append(
            _Bucket(
                label=bucket_month.strftime("%Y-%m"),
                counts={category: 0 for category in _CATEGORIES},
            )
        )
    return buckets


def _build_week_buckets(*, now: datetime) -> list[_Bucket]:
    start_of_week = now.date() - timedelta(days=now.weekday())
    buckets = []
    for offset in range(-11, 1):
        bucket_week = start_of_week + timedelta(weeks=offset)
        iso = bucket_week.isocalendar()
        label = f"{iso.year}-W{iso.week:02d}"
        buckets.append(
            _Bucket(label=label, counts={category: 0 for category in _CATEGORIES})
        )
    return buckets


def _build_day_buckets(*, now: datetime) -> list[_Bucket]:
    buckets = []
    for offset in range(-29, 1):
        bucket_day = now.date() + timedelta(days=offset)
        buckets.append(
            _Bucket(
                label=bucket_day.strftime("%Y-%m-%d"),
                counts={category: 0 for category in _CATEGORIES},
            )
        )
    return buckets


def _build_activity_day_buckets(*, now: datetime) -> list[_Bucket]:
    buckets = []
    for offset in range(-364, 1):
        bucket_day = now.date() + timedelta(days=offset)
        buckets.append(
            _Bucket(
                label=bucket_day.strftime("%Y-%m-%d"),
                counts={category: 0 for category in _CATEGORIES},
            )
        )
    return buckets


def _aggregate_activity(
    events: list[_ActivityEvent],
    *,
    now: datetime | None = None,
) -> dict[str, list[_Bucket]]:
    current = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    all_values = [event.occurred_at for event in events]

    years = _build_year_buckets(all_values, now=current)
    months = _build_month_buckets(now=current)
    weeks = _build_week_buckets(now=current)
    days = _build_day_buckets(now=current)
    activity_days = _build_activity_day_buckets(now=current)

    year_index = {bucket.label: bucket for bucket in years}
    month_index = {bucket.label: bucket for bucket in months}
    week_index = {bucket.label: bucket for bucket in weeks}
    day_index = {bucket.label: bucket for bucket in days}
    activity_day_index = {bucket.label: bucket for bucket in activity_days}

    for event in events:
        if event.category not in _CATEGORIES or event.count < 1:
            continue
        utc = event.occurred_at.astimezone(timezone.utc)
        year_label = str(utc.year)
        month_label = utc.strftime("%Y-%m")
        iso = utc.date().isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"
        day_label = utc.strftime("%Y-%m-%d")

        if year_bucket := year_index.get(year_label):
            year_bucket.counts[event.category] += event.count
        if month_bucket := month_index.get(month_label):
            month_bucket.counts[event.category] += event.count
        if week_bucket := week_index.get(week_label):
            week_bucket.counts[event.category] += event.count
        if day_bucket := day_index.get(day_label):
            day_bucket.counts[event.category] += event.count
        if activity_day_bucket := activity_day_index.get(day_label):
            activity_day_bucket.counts[event.category] += event.count

    return {
        "years": years,
        "months_last_12": months,
        "weeks_last_12": weeks,
        "days_last_30": days,
        "days_last_365": activity_days,
    }

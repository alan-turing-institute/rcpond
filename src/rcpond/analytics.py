"""Analytics over RCPond ticket history.

Computes performance metrics about RCPond directly from ServiceNow ticket history
(there is no separate datastore). The public API is:

- `DurationStats`: summary statistics for a set of time intervals.
- `TicketTypeMetrics`: per-ticket-type metric counts and statistics.
- `compute_metrics`: group tickets by type and compute the metrics.
- `render_markdown`: render the metrics as a markdown report.

Metrics are reported per ticket type (via `servicenow.ticket_type_key`). See
planning/analytics.md for the staged metric roadmap. Implemented so far:

Stage 1 (counts):

- total tickets
- tickets processed by RCPond (>= 1 RCPond note)
- tickets processed manually (>= 1 manual note and no RCPond note)
- RCPond-processed tickets that also had a subsequent manual interaction

Stage 2 (distributions and time intervals):

- distribution of RCPond interactions per ticket
- distribution of manual interactions per ticket
- time from creation to first RCPond interaction
- time from creation to first manual interaction
- time from creation to final resolution (closed/resolved/cancelled only)
- time from first RCPond interaction to final resolution

Durations are summarised as ``DurationStats`` (in days). Tickets that do not
qualify for a given interval (e.g. an open ticket has no resolution time) are
simply excluded from that interval's statistics.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from rcpond.servicenow import Ticket, ticket_type_key

## --------------------------------------------------------------------------------
## Metric data structures


@dataclass(frozen=True)
class DurationStats:
    """Summary statistics for a set of time intervals, in days.

    >>> stats.count, stats.median_days
    """

    count: int
    """Number of tickets that contributed to these statistics."""
    median_days: float
    """Median interval length in days."""
    mean_days: float
    """Mean interval length in days."""
    min_days: float
    """Shortest interval in days."""
    max_days: float
    """Longest interval in days."""


@dataclass(frozen=True)
class TicketTypeMetrics:
    """Analytics metrics for a single ticket type.

    >>> metrics.type_key, metrics.rcpond_processed
    """

    type_key: str
    """The ``_TICKET_TYPES`` registry key these metrics describe."""
    total_tickets: int
    """Total tickets of this type included in the report."""

    ## Stage 1: processing-mix counts
    rcpond_processed: int
    """Tickets with at least one RCPond note (any version)."""
    manually_processed: int
    """Tickets with at least one manual note and no RCPond note."""
    rcpond_with_subsequent_manual: int
    """RCPond-processed tickets that also had a manual note after RCPond's first note."""

    ## Stage 2: interaction distributions (interaction count -> number of tickets, sorted by count)
    rcpond_interaction_distribution: dict[int, int]
    """How many tickets had 0, 1, 2, ... RCPond notes."""
    manual_interaction_distribution: dict[int, int]
    """How many tickets had 0, 1, 2, ... manual notes."""

    ## Stage 2: time intervals (None when no ticket qualifies)
    time_to_first_rcpond: DurationStats | None
    """Creation to first RCPond interaction."""
    time_to_first_manual: DurationStats | None
    """Creation to first manual interaction."""
    time_to_resolution: DurationStats | None
    """Creation to final resolution (closed/resolved/cancelled tickets only)."""
    time_first_rcpond_to_resolution: DurationStats | None
    """First RCPond interaction to final resolution."""


## --------------------------------------------------------------------------------
## Interface to this module


def compute_metrics(tickets: list[Ticket]) -> list[TicketTypeMetrics]:
    """Group ``tickets`` by ticket type and compute the metrics.

    Tickets whose type is not in the registry (``ticket_type_key`` returns
    ``None``) are skipped, since per-type metrics are not meaningful for them.
    Results are sorted by ``type_key`` for stable, reproducible output.

    Parameters
    ----------
    tickets : list[Ticket]
        Base tickets with ``work_notes``/``comments``/``state``/``opened_at``
        populated, e.g. from ``ServiceNow.get_tickets(state=TicketState.all_including_closed)``.

    Returns
    -------
    list[TicketTypeMetrics]
        One entry per ticket type present, sorted by ``type_key``.
    """
    by_type: dict[str, list[Ticket]] = {}
    for t in tickets:
        key = ticket_type_key(t)
        if key is None:
            continue
        by_type.setdefault(key, []).append(t)

    return [_metrics_for_type(key, by_type[key]) for key in sorted(by_type)]


def render_markdown(metrics: list[TicketTypeMetrics]) -> str:
    """Render metrics as a markdown report.

    The report has a processing-mix summary table (one row per ticket type, with a
    labelled cross-type aggregate row when more than one type is present), followed
    by per-type interaction-distribution and time-interval sections.

    Parameters
    ----------
    metrics : list[TicketTypeMetrics]
        Per-type metrics as returned by ``compute_metrics``.

    Returns
    -------
    str
        A markdown document ending in a trailing newline.
    """
    lines = ["# RCPond analytics report", ""]

    if not metrics:
        lines += ["## Ticket processing", "", "_No tickets found._"]
        return "\n".join(lines) + "\n"

    lines += _render_processing_table(metrics)
    lines += _render_interaction_distributions(metrics)
    lines += _render_time_intervals(metrics)
    return "\n".join(lines) + "\n"


## --------------------------------------------------------------------------------
## Internal helpers: metric computation


def _metrics_for_type(type_key: str, group: list[Ticket]) -> TicketTypeMetrics:
    """Compute all implemented metrics for a single ticket type's tickets."""
    return TicketTypeMetrics(
        type_key=type_key,
        total_tickets=len(group),
        rcpond_processed=sum(1 for t in group if t.rcpond_note_count() > 0),
        manually_processed=sum(1 for t in group if t.rcpond_note_count() == 0 and t.manual_note_count() > 0),
        rcpond_with_subsequent_manual=sum(1 for t in group if t.has_subsequent_manual_interaction()),
        rcpond_interaction_distribution=_distribution(t.rcpond_note_count() for t in group),
        manual_interaction_distribution=_distribution(t.manual_note_count() for t in group),
        time_to_first_rcpond=_duration_stats(
            _deltas_days(group, lambda t: t.opened_datetime(), lambda t: t.first_rcpond_note_datetime())
        ),
        time_to_first_manual=_duration_stats(
            _deltas_days(group, lambda t: t.opened_datetime(), lambda t: t.first_manual_note_datetime())
        ),
        time_to_resolution=_duration_stats(
            _deltas_days(group, lambda t: t.opened_datetime(), lambda t: t.resolution_datetime())
        ),
        time_first_rcpond_to_resolution=_duration_stats(
            _deltas_days(group, lambda t: t.first_rcpond_note_datetime(), lambda t: t.resolution_datetime())
        ),
    )


def _distribution(counts: Iterable[int]) -> dict[int, int]:
    """Tally ``counts`` into a {value: occurrences} dict, sorted by value."""
    return dict(sorted(Counter(counts).items()))


def _deltas_days(
    group: list[Ticket],
    start: Callable[[Ticket], datetime | None],
    end: Callable[[Ticket], datetime | None],
) -> list[float]:
    """Return the ``end - start`` interval, in days, for each ticket where both ends exist."""
    deltas: list[float] = []
    for t in group:
        s, e = start(t), end(t)
        if s is not None and e is not None:
            deltas.append((e - s).total_seconds() / 86400.0)
    return deltas


def _duration_stats(deltas_days: list[float]) -> DurationStats | None:
    """Summarise interval lengths, or ``None`` if no ticket qualified."""
    if not deltas_days:
        return None
    return DurationStats(
        count=len(deltas_days),
        median_days=round(statistics.median(deltas_days), 2),
        mean_days=round(statistics.mean(deltas_days), 2),
        min_days=round(min(deltas_days), 2),
        max_days=round(max(deltas_days), 2),
    )


## --------------------------------------------------------------------------------
## Internal helpers: rendering


def _render_processing_table(metrics: list[TicketTypeMetrics]) -> list[str]:
    """Stage 1 processing-mix table, with a labelled aggregate row for multiple types."""
    header = ["Ticket type", "Total tickets", "Processed by RCPond", "Processed manually", "RCPond + subsequent manual"]
    lines = ["## Ticket processing", "", "| " + " | ".join(header) + " |", "| --- | ---: | ---: | ---: | ---: |"]
    lines += [
        _row(m.type_key, m.total_tickets, m.rcpond_processed, m.manually_processed, m.rcpond_with_subsequent_manual)
        for m in metrics
    ]
    ## A cross-type total is only meaningful (and non-redundant) with multiple types.
    if len(metrics) > 1:
        lines.append(
            _row(
                "**All types (aggregate)**",
                sum(m.total_tickets for m in metrics),
                sum(m.rcpond_processed for m in metrics),
                sum(m.manually_processed for m in metrics),
                sum(m.rcpond_with_subsequent_manual for m in metrics),
            )
        )
    return lines


def _render_interaction_distributions(metrics: list[TicketTypeMetrics]) -> list[str]:
    """Per-type table of how many tickets had each interaction count."""
    lines = ["", "## Interaction distributions"]
    for m in metrics:
        counts = sorted(set(m.rcpond_interaction_distribution) | set(m.manual_interaction_distribution))
        lines += [
            "",
            f"### {m.type_key}",
            "",
            "| Interactions | Tickets (RCPond) | Tickets (manual) |",
            "| ---: | ---: | ---: |",
        ]
        lines += [
            f"| {n} | {m.rcpond_interaction_distribution.get(n, 0)} | {m.manual_interaction_distribution.get(n, 0)} |"
            for n in counts
        ]
    return lines


def _render_time_intervals(metrics: list[TicketTypeMetrics]) -> list[str]:
    """Per-type table of time-interval statistics (in days)."""
    lines = ["", "## Time intervals (days)"]
    for m in metrics:
        lines += [
            "",
            f"### {m.type_key}",
            "",
            "| Interval | n | Median | Mean | Min | Max |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            _stats_row("Creation → first RCPond", m.time_to_first_rcpond),
            _stats_row("Creation → first manual", m.time_to_first_manual),
            _stats_row("Creation → resolution", m.time_to_resolution),
            _stats_row("First RCPond → resolution", m.time_first_rcpond_to_resolution),
        ]
    return lines


def _row(label: str, total: int, rcpond: int, manual: int, subsequent: int) -> str:
    """Format a single processing-mix table row for a ticket type (or the aggregate)."""
    return f"| {label} | {total} | {rcpond} | {manual} | {subsequent} |"


def _stats_row(label: str, stats: DurationStats | None) -> str:
    """Format a single time-interval row; an em dash marks intervals with no qualifying tickets."""
    if stats is None:
        return f"| {label} | 0 | — | — | — | — |"
    return (
        f"| {label} | {stats.count} | {stats.median_days} | {stats.mean_days} | {stats.min_days} | {stats.max_days} |"
    )

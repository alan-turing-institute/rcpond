"""Analytics over RCPond ticket history.

Computes performance metrics about RCPond directly from ServiceNow ticket history
(there is no separate datastore). The public API is:

- `TicketTypeMetrics`: per-ticket-type Stage 1 metric counts.
- `compute_stage1_metrics`: group tickets by type and compute the counts.

Metrics are reported per ticket type (via `servicenow.ticket_type_key`). See
planning/analytics.md for the staged metric roadmap; only Stage 1 is implemented.
The result dataclass and the group-then-compute structure are intended to be
extended for Stages 2-4 without reworking the existing code.

Stage 1 metrics (per ticket type):

- total tickets
- tickets processed by RCPond (>= 1 RCPond note)
- tickets processed manually (>= 1 manual note and no RCPond note)
- RCPond-processed tickets that also had a subsequent manual interaction
"""

from __future__ import annotations

from dataclasses import dataclass

from rcpond.servicenow import Ticket, ticket_type_key

## --------------------------------------------------------------------------------
## Metric data structures


@dataclass(frozen=True)
class TicketTypeMetrics:
    """Stage 1 analytics counts for a single ticket type.

    >>> metrics.type_key, metrics.rcpond_processed
    """

    type_key: str
    """The ``_TICKET_TYPES`` registry key these metrics describe."""
    total_tickets: int
    """Total tickets of this type included in the report."""
    rcpond_processed: int
    """Tickets with at least one RCPond note (any version)."""
    manually_processed: int
    """Tickets with at least one manual note and no RCPond note."""
    rcpond_with_subsequent_manual: int
    """RCPond-processed tickets that also had a manual note after RCPond's first note."""


## --------------------------------------------------------------------------------
## Interface to this module


def compute_stage1_metrics(tickets: list[Ticket]) -> list[TicketTypeMetrics]:
    """Group ``tickets`` by ticket type and compute the Stage 1 metric counts.

    Tickets whose type is not in the registry (``ticket_type_key`` returns
    ``None``) are skipped, since per-type metrics are not meaningful for them.
    Results are sorted by ``type_key`` for stable, reproducible output.

    Parameters
    ----------
    tickets : list[Ticket]
        Base tickets with ``work_notes``/``comments`` populated, e.g. from
        ``ServiceNow.get_tickets(state=TicketState.all_including_closed)``.

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
    """Render Stage 1 metrics as a markdown report.

    Produces one table row per ticket type. When more than one type is present a
    final aggregate row (summing the counts across all types) is appended and
    clearly labelled, per planning/analytics.md.

    Parameters
    ----------
    metrics : list[TicketTypeMetrics]
        Per-type metrics as returned by ``compute_stage1_metrics``.

    Returns
    -------
    str
        A markdown document ending in a trailing newline.
    """
    lines = ["# RCPond analytics report", "", "## Ticket processing (Stage 1)", ""]

    if not metrics:
        lines.append("_No tickets found._")
        return "\n".join(lines) + "\n"

    header = ["Ticket type", "Total tickets", "Processed by RCPond", "Processed manually", "RCPond + subsequent manual"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
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

    return "\n".join(lines) + "\n"


## --------------------------------------------------------------------------------
## Internal helpers


def _row(label: str, total: int, rcpond: int, manual: int, subsequent: int) -> str:
    """Format a single markdown table row for a ticket type (or the aggregate)."""
    return f"| {label} | {total} | {rcpond} | {manual} | {subsequent} |"


def _metrics_for_type(type_key: str, group: list[Ticket]) -> TicketTypeMetrics:
    """Compute the Stage 1 counts for a single ticket type's tickets."""
    return TicketTypeMetrics(
        type_key=type_key,
        total_tickets=len(group),
        rcpond_processed=sum(1 for t in group if t.rcpond_note_count() > 0),
        manually_processed=sum(1 for t in group if t.rcpond_note_count() == 0 and t.manual_note_count() > 0),
        rcpond_with_subsequent_manual=sum(1 for t in group if t.has_subsequent_manual_interaction()),
    )

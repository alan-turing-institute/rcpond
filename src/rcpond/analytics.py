"""Analytics over RCPond ticket history.

Computes performance metrics about RCPond directly from ServiceNow ticket history
(there is no separate datastore). The public API is:

- `Period`: granularity for the over-time trend tables.
- `build_ticket_frame`: turn a list of tickets into a one-row-per-ticket DataFrame.
- `render_markdown`: render the metrics from that DataFrame as a markdown report.

This module is part of the optional ``html`` dependency group (it requires ``pandas``
and ``tabulate``). All grouping/aggregation is delegated to pandas; the per-ticket
feature extraction lives on ``Ticket`` (see ``servicenow.py``). See
planning/analytics.md for the staged metric roadmap and design decisions.

The report has four sections, each per ticket type:

- **Ticket processing** — counts: total, processed by RCPond, processed manually,
  RCPond-processed with a subsequent manual interaction (plus a cross-type aggregate).
- **Interaction distributions** — how many tickets had 0, 1, 2, ... RCPond / manual notes.
- **Time intervals (days)** — n/median/mean/min/max for creation→first RCPond,
  creation→first manual, creation→resolution, and first RCPond→resolution.
- **Trends** — the processing counts plus median resolution time, bucketed by the
  ticket's creation period (month/quarter/year).
"""

from __future__ import annotations

from enum import Enum

import pandas as pd

from rcpond.servicenow import Ticket, ticket_type_key


class Period(str, Enum):
    """Granularity for the over-time trend tables.

    >>> Period.quarter.value
    'quarter'
    """

    month = "month"
    quarter = "quarter"
    year = "year"


## Per-row columns produced directly from the Ticket helpers (before derived durations).
_BASE_COLUMNS = [
    "type_key",
    "opened",
    "rcpond_notes",
    "manual_notes",
    "processed_by_rcpond",
    "processed_manually",
    "subsequent_manual",
    "still_open",
    "first_rcpond",
    "first_manual",
    "resolution",
]

## Datetime columns (parsed to datetime64 so pandas date arithmetic works).
_DATETIME_COLUMNS = ["opened", "first_rcpond", "first_manual", "resolution"]

## Derived duration columns, in days: (end - start). NaN when either endpoint is missing.
_DURATION_COLUMNS = {
    "days_to_first_rcpond": ("opened", "first_rcpond"),
    "days_to_first_manual": ("opened", "first_manual"),
    "days_to_resolution": ("opened", "resolution"),
    "days_rcpond_to_resolution": ("first_rcpond", "resolution"),
}

## Friendly labels for the time-interval table rows.
_INTERVAL_LABELS = {
    "days_to_first_rcpond": "Creation → first RCPond",
    "days_to_first_manual": "Creation → first manual",
    "days_to_resolution": "Creation → resolution",
    "days_rcpond_to_resolution": "First RCPond → resolution",
}

## Period -> pandas ``to_period`` frequency code.
_PERIOD_FREQ = {Period.month: "M", Period.quarter: "Q", Period.year: "Y"}


## --------------------------------------------------------------------------------
## Interface to this module


def build_ticket_frame(tickets: list[Ticket]) -> pd.DataFrame:
    """Build a one-row-per-ticket DataFrame from the per-ticket ``Ticket`` helpers.

    Tickets whose type is not in the registry (``ticket_type_key`` returns ``None``)
    are excluded, since per-type metrics are not meaningful for them. The columns are
    the de-facto analytics schema: ``type_key``; ``opened``/``first_rcpond``/
    ``first_manual``/``resolution`` (datetime64, ``NaT`` when absent or, for resolution,
    when the ticket is still open); ``rcpond_notes``/``manual_notes`` (int);
    ``processed_by_rcpond``/``processed_manually``/``subsequent_manual``/``still_open``
    (bool); and the derived ``days_to_*`` duration columns (float days, ``NaN`` when an
    endpoint is missing).

    Parameters
    ----------
    tickets : list[Ticket]
        Base tickets with ``work_notes``/``comments``/``state``/``opened_at`` populated,
        e.g. from ``ServiceNow.get_tickets(state=TicketState.all_including_closed)``.

    Returns
    -------
    pandas.DataFrame
    """
    rows = []
    for t in tickets:
        key = ticket_type_key(t)
        if key is None:
            continue
        rcpond_notes = t.rcpond_note_count()
        manual_notes = t.manual_note_count()
        rows.append(
            {
                "type_key": key,
                "opened": t.opened_datetime(),
                "rcpond_notes": rcpond_notes,
                "manual_notes": manual_notes,
                "processed_by_rcpond": rcpond_notes > 0,
                "processed_manually": rcpond_notes == 0 and manual_notes > 0,
                "subsequent_manual": t.has_subsequent_manual_interaction(),
                "still_open": not t.is_closed(),
                "first_rcpond": t.first_rcpond_note_datetime(),
                "first_manual": t.first_manual_note_datetime(),
                "resolution": t.resolution_datetime(),
            }
        )

    df = pd.DataFrame(rows, columns=_BASE_COLUMNS)
    for col in _DATETIME_COLUMNS:
        df[col] = pd.to_datetime(df[col])
    for name, (start, end) in _DURATION_COLUMNS.items():
        df[name] = (df[end] - df[start]).dt.total_seconds() / 86400.0
    return df


def render_markdown(df: pd.DataFrame, period: Period = Period.quarter) -> str:
    """Render the analytics report as markdown from a ticket DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        A frame from ``build_ticket_frame``.
    period : Period
        Granularity for the trends section.

    Returns
    -------
    str
        A markdown document ending in a trailing newline.
    """
    lines = ["# RCPond analytics report", ""]
    if df.empty:
        lines += ["## Ticket processing", "", "_No tickets found._"]
        return "\n".join(lines) + "\n"

    lines += _processing_section(df)
    lines += _distribution_section(df)
    lines += _intervals_section(df)
    lines += _trends_section(df, period)
    return "\n".join(lines) + "\n"


## --------------------------------------------------------------------------------
## Internal helpers: rendering


def _md(frame: pd.DataFrame) -> str:
    """Render a frame as a GitHub-flavoured markdown table.

    Floats show 2 dp (right-aligned by tabulate); missing values render as ``nan``.
    """
    return frame.to_markdown(index=False, floatfmt=".2f")


def _processing_section(df: pd.DataFrame) -> list[str]:
    """Processing-mix counts per type, with a labelled cross-type aggregate for >1 type."""
    agg = df.groupby("type_key").agg(
        total=("type_key", "size"),
        still_open=("still_open", "sum"),
        rcpond=("processed_by_rcpond", "sum"),
        manual=("processed_manually", "sum"),
        subsequent=("subsequent_manual", "sum"),
    )
    agg = agg.reset_index()
    ## A cross-type total is only meaningful (and non-redundant) with multiple types.
    if len(agg) > 1:
        totals = agg.drop(columns="type_key").sum()
        totals["type_key"] = "**All types (aggregate)**"
        agg = pd.concat([agg, totals.to_frame().T[agg.columns]], ignore_index=True)
    agg = agg.rename(
        columns={
            "type_key": "Ticket type",
            "total": "Total tickets",
            "still_open": "Still open",
            "rcpond": "Processed by RCPond",
            "manual": "Processed manually",
            "subsequent": "RCPond + subsequent manual",
        }
    )
    return ["## Ticket processing", "", _md(agg), ""]


def _distribution_section(df: pd.DataFrame) -> list[str]:
    """Per type: how many tickets had each interaction count (RCPond and manual side by side)."""
    lines = ["## Interaction distributions", ""]
    for type_key, sub in df.groupby("type_key"):
        dist = pd.DataFrame(
            {
                "Tickets (RCPond)": sub["rcpond_notes"].value_counts(),
                "Tickets (manual)": sub["manual_notes"].value_counts(),
            }
        )
        dist = dist.fillna(0).astype(int).sort_index()
        dist.index.name = "Interactions"
        lines += [f"### {type_key}", "", _md(dist.reset_index()), ""]
    return lines


def _intervals_section(df: pd.DataFrame) -> list[str]:
    """Per type: n/median/mean/min/max (days) for each time interval."""
    lines = ["## Time intervals (days)", ""]
    cols = list(_INTERVAL_LABELS)
    for type_key, sub in df.groupby("type_key"):
        stats = sub[cols].agg(["count", "median", "mean", "min", "max"]).T
        stats["count"] = stats["count"].astype(int)
        stats.index = pd.Index([_INTERVAL_LABELS[c] for c in stats.index], name="Interval")
        stats = stats.reset_index().rename(
            columns={"count": "n", "median": "Median", "mean": "Mean", "min": "Min", "max": "Max"}
        )
        lines += [f"### {type_key}", "", _md(stats), ""]
    return lines


def _trends_section(df: pd.DataFrame, period: Period) -> list[str]:
    """Per type: processing counts plus median resolution, bucketed by creation period."""
    lines = [f"## Trends by {period.value}", ""]
    df = df.assign(period=df["opened"].dt.to_period(_PERIOD_FREQ[period]))
    for type_key, sub in df.groupby("type_key"):
        trend = (
            sub.dropna(subset=["period"])
            .groupby("period")
            .agg(
                total=("type_key", "size"),
                still_open=("still_open", "sum"),
                rcpond=("processed_by_rcpond", "sum"),
                manual=("processed_manually", "sum"),
                subsequent=("subsequent_manual", "sum"),
                median_resolution=("days_to_resolution", "median"),
            )
        )
        trend = trend.reset_index()
        ## PeriodIndex renders quarters as "2026Q1"; use the documented "2026-Q1" form.
        trend["period"] = trend["period"].astype(str).str.replace("Q", "-Q")
        trend = trend.rename(
            columns={
                "period": "Period",
                "total": "Total",
                "still_open": "Still open",
                "rcpond": "Processed by RCPond",
                "manual": "Processed manually",
                "subsequent": "RCPond + subsequent",
                "median_resolution": "Median resolution (days)",
            }
        )
        lines += [f"### {type_key}", "", _md(trend), ""]
    return lines

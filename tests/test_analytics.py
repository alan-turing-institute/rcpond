from unittest.mock import MagicMock, patch

import pandas as pd

from rcpond import command, servicenow
from rcpond.analytics import Period, build_ticket_frame, render_markdown
from rcpond.servicenow import Ticket, TicketState

## short_description that matches ComputeAllocationRequestTicket.MATCH_CRITERIA
_CART_DESC = "Request access to HPC and cloud computing facilities"


def _note(ts: str, user: str, content: str, note_type: str = "Work notes") -> str:
    return f"{ts} - {user} ({note_type})\n{content}"


def _rcpond(ts: str) -> str:
    return _note(ts, "RCPond", servicenow._note_prefix("post_freeform_note") + "Response")


def _ticket(
    number: str,
    *,
    work_notes: str = "",
    comments: str = "",
    short_description: str = _CART_DESC,
    state: str = "New",
    opened_at: str = "01/01/2026 09:00:00",
) -> Ticket:
    return Ticket(
        sys_id=number,
        number=number,
        opened_at=opened_at,
        requested_for="",
        u_category="",
        u_sub_category="",
        short_description=short_description,
        state=state,
        assigned_to="",
        work_notes=work_notes,
        comments=comments,
    )


def _table_rows(md: str) -> list[list[str]]:
    """Extract markdown table rows as lists of stripped cell strings (padding-agnostic)."""
    rows = []
    for line in md.splitlines():
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


## A synthetic render frame: only the columns render_markdown consumes, with defaults.
def _frame(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "type_key": "compute_allocation_request",
        "opened": "2026-01-01",
        "rcpond_notes": 0,
        "manual_notes": 0,
        "processed_by_rcpond": False,
        "processed_manually": False,
        "subsequent_manual": False,
        "still_open": True,
        "days_to_first_rcpond": float("nan"),
        "days_to_first_manual": float("nan"),
        "days_to_resolution": float("nan"),
        "days_rcpond_to_resolution": float("nan"),
    }
    df = pd.DataFrame([{**defaults, **r} for r in rows])
    df["opened"] = pd.to_datetime(df["opened"])
    return df


## ── build_ticket_frame ──────────────────────────────────────────────────────


def test_build_ticket_frame_excludes_unknown_type_and_derives_columns():
    closed = _ticket(
        "A",
        work_notes=_rcpond("01/01/2026 10:00:00"),
        comments=_note("03/01/2026 09:00:00", "System", "auto close", "Additional comments"),
        state="Closed",
        opened_at="01/01/2026 09:00:00",
    )
    manual = _ticket("B", work_notes=_note("16/05/2026 09:00:00", "Alice", "human"), opened_at="15/05/2026 09:00:00")
    empty = _ticket("C", opened_at="20/08/2026 09:00:00")
    unknown = _ticket("D", work_notes=_rcpond("01/01/2026 10:00:00"), short_description="A different request")

    df = build_ticket_frame([closed, manual, empty, unknown])

    ## Unknown-type ticket is excluded; order is preserved for the rest.
    assert list(df["type_key"]) == ["compute_allocation_request"] * 3

    ## Closed ticket: RCPond-processed, not still open; resolution = final (System) note → 2 days after opening.
    assert bool(df.iloc[0]["processed_by_rcpond"]) is True
    assert bool(df.iloc[0]["still_open"]) is False
    assert df.iloc[0]["days_to_resolution"] == 2.0

    ## Manual, still open: manually processed; no resolution → NaN duration.
    assert bool(df.iloc[1]["processed_manually"]) is True
    assert bool(df.iloc[1]["still_open"]) is True
    assert pd.isna(df.iloc[1]["days_to_resolution"])

    ## No notes: neither RCPond nor manual.
    assert int(df.iloc[2]["rcpond_notes"]) == 0
    assert int(df.iloc[2]["manual_notes"]) == 0


def test_build_ticket_frame_empty_returns_empty_frame_with_schema():
    df = build_ticket_frame([])
    assert df.empty
    assert "days_to_resolution" in df.columns


## ── render_markdown: processing ─────────────────────────────────────────────


def test_render_empty():
    out = render_markdown(build_ticket_frame([]))
    assert "_No tickets found._" in out
    assert out.endswith("\n")


def test_render_processing_with_cross_type_aggregate():
    df = _frame(
        [
            {"type_key": "compute_allocation_request", "processed_by_rcpond": True},
            {"type_key": "compute_allocation_request", "processed_manually": True},
            {"type_key": "github_org_membership", "processed_by_rcpond": True, "subsequent_manual": True},
        ]
    )
    rows = _table_rows(render_markdown(df))
    ## Ticket type | Total | Still open | Processed by RCPond | Processed manually | RCPond + subsequent
    assert ["compute_allocation_request", "2", "2", "1", "1", "0"] in rows
    assert ["github_org_membership", "1", "1", "1", "0", "1"] in rows
    ## Aggregate sums each column across types and is clearly labelled.
    assert ["**All types (aggregate)**", "3", "3", "2", "1", "1"] in rows


def test_render_processing_single_type_has_no_aggregate():
    out = render_markdown(_frame([{"processed_by_rcpond": True}]))
    assert "aggregate" not in out.lower()


## ── render_markdown: distributions ──────────────────────────────────────────


def test_render_interaction_distributions():
    df = _frame(
        [
            {"rcpond_notes": 1, "manual_notes": 0},
            {"rcpond_notes": 0, "manual_notes": 2},
            {"rcpond_notes": 1, "manual_notes": 2},
        ]
    )
    rows = _table_rows(render_markdown(df))
    ## Interactions | Tickets (RCPond) | Tickets (manual)
    assert ["0", "1", "1"] in rows
    assert ["1", "2", "0"] in rows
    assert ["2", "0", "2"] in rows


## ── render_markdown: time intervals ─────────────────────────────────────────


def test_render_time_intervals_with_dash_for_empty_interval():
    df = _frame(
        [
            {"days_to_first_rcpond": 0.04, "days_to_resolution": 2.0, "days_rcpond_to_resolution": 1.96},
            {"days_to_first_rcpond": 1.0, "days_to_resolution": 4.0, "days_rcpond_to_resolution": 3.0},
        ]
    )
    rows = _table_rows(render_markdown(df))
    ## Interval | n | Median | Mean | Min | Max
    assert ["Creation → first RCPond", "2", "0.52", "0.52", "0.04", "1.00"] in rows
    ## No manual notes anywhere → interval has no qualifying tickets (default NaN rendering).
    assert ["Creation → first manual", "0", "nan", "nan", "nan", "nan"] in rows


## ── render_markdown: trends ─────────────────────────────────────────────────


def test_render_trends_quarter_buckets_and_dash():
    df = _frame(
        [
            {"opened": "2026-02-01", "processed_by_rcpond": True, "still_open": False, "days_to_resolution": 2.0},
            {"opened": "2026-05-01", "processed_manually": True, "still_open": True},
        ]
    )
    rows = _table_rows(render_markdown(df, Period.quarter))
    ## Period | Total | Still open | Processed by RCPond | Processed manually | RCPond + subsequent | Median resolution
    assert ["2026-Q1", "1", "0", "1", "0", "0", "2.00"] in rows
    ## Q2 has no closed tickets → still open, and no median resolution (default NaN rendering).
    assert ["2026-Q2", "1", "1", "0", "1", "0", "nan"] in rows


def test_render_trends_period_labels():
    df = _frame([{"opened": "2026-08-07"}])
    assert any(r[0] == "2026-08" for r in _table_rows(render_markdown(df, Period.month)))
    assert any(r[0] == "2026-Q3" for r in _table_rows(render_markdown(df, Period.quarter)))
    assert any(r[0] == "2026" for r in _table_rows(render_markdown(df, Period.year)))


def test_render_includes_all_section_headings():
    out = render_markdown(_frame([{"processed_by_rcpond": True}]), Period.quarter)
    assert "## Ticket processing" in out
    assert "## Interaction distributions" in out
    assert "## Time intervals (days)" in out
    assert "## Trends by quarter" in out


## ── command.analytics wiring ────────────────────────────────────────────────


def test_command_analytics_fetches_all_states_prints_and_returns_markdown(capsys):
    tickets = [_ticket("A", work_notes=_rcpond("02/01/2026 10:00:00"), opened_at="01/01/2026 09:00:00")]
    with patch("rcpond.command.ServiceNow") as MockSN:
        MockSN.return_value.get_tickets.return_value = tickets
        out = command.analytics(config=MagicMock())

    MockSN.return_value.get_tickets.assert_called_once_with(state=TicketState.all_including_closed)
    assert "# RCPond analytics report" in out
    assert "## Trends by quarter" in out
    assert out == capsys.readouterr().out

from unittest.mock import MagicMock, patch

from rcpond import command, servicenow
from rcpond.analytics import DurationStats, TicketTypeMetrics, compute_metrics, render_markdown
from rcpond.servicenow import Ticket, TicketState

## short_description that matches ComputeAllocationRequestTicket.MATCH_CRITERIA
_CART_DESC = "Request access to HPC and cloud computing facilities"


def _note(ts: str, user: str, content: str, note_type: str = "Work notes") -> str:
    return f"{ts} - {user} ({note_type})\n{content}"


_RCPOND = _note("01/01/2026 10:00:00", "RCPond", servicenow._note_prefix("post_freeform_note") + "Response")
_HUMAN = _note("01/01/2026 11:00:00", "Alice", "A human work note")
_SYSTEM = _note("01/01/2026 12:00:00", "System", "Automatically closed.", note_type="Additional comments")


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


def _make_metrics(**overrides) -> TicketTypeMetrics:
    """Build a TicketTypeMetrics with sensible defaults for rendering tests."""
    base = {
        "type_key": "compute_allocation_request",
        "total_tickets": 5,
        "rcpond_processed": 3,
        "manually_processed": 1,
        "rcpond_with_subsequent_manual": 1,
        "rcpond_interaction_distribution": {0: 2, 1: 3},
        "manual_interaction_distribution": {0: 1, 1: 4},
        "time_to_first_rcpond": DurationStats(3, 0.04, 0.05, 0.01, 0.1),
        "time_to_first_manual": None,
        "time_to_resolution": DurationStats(2, 1.0, 1.5, 0.5, 2.5),
        "time_first_rcpond_to_resolution": DurationStats(1, 0.9, 0.9, 0.9, 0.9),
    }
    base.update(overrides)
    return TicketTypeMetrics(**base)


## ── compute_metrics: Stage 1 counts ─────────────────────────────────────────


def test_compute_metrics_empty():
    assert compute_metrics([]) == []


def test_compute_metrics_skips_unknown_type():
    """Tickets whose short_description matches no registered type are excluded entirely."""
    unknown = _ticket("RES0000001", work_notes=_RCPOND, short_description="Some other request")
    assert compute_metrics([unknown]) == []


def test_compute_metrics_stage1_counts():
    tickets = [
        _ticket("RES0000001", work_notes=_RCPOND),  ## RCPond only
        _ticket("RES0000002", work_notes=_HUMAN),  ## manual only
        _ticket("RES0000003", work_notes="\n".join([_RCPOND, _HUMAN])),  ## RCPond + subsequent manual
        _ticket("RES0000004"),  ## no notes: neither RCPond nor manual
        _ticket("RES0000005", work_notes=_RCPOND, comments=_SYSTEM),  ## RCPond + System (automated, not manual)
    ]

    [m] = compute_metrics(tickets)

    assert m.type_key == "compute_allocation_request"
    assert m.total_tickets == 5
    assert m.rcpond_processed == 3  ## tickets 1, 3, 5
    assert m.manually_processed == 1  ## ticket 2 (4 has no notes; 5 has RCPond)
    assert m.rcpond_with_subsequent_manual == 1  ## ticket 3 only (5's System note is not manual)


## ── compute_metrics: Stage 2 distributions ──────────────────────────────────


def test_compute_metrics_interaction_distributions():
    tickets = [
        _ticket("RES0000001", work_notes=_RCPOND),  ## rcpond=1, manual=0
        _ticket("RES0000002", work_notes=_HUMAN),  ## rcpond=0, manual=1
        _ticket("RES0000003", work_notes="\n".join([_RCPOND, _HUMAN])),  ## rcpond=1, manual=1
        _ticket("RES0000004"),  ## rcpond=0, manual=0
    ]

    [m] = compute_metrics(tickets)

    assert m.rcpond_interaction_distribution == {0: 2, 1: 2}
    assert m.manual_interaction_distribution == {0: 2, 1: 2}


## ── compute_metrics: Stage 2 time intervals ─────────────────────────────────


def test_compute_metrics_time_intervals_closed_ticket():
    ## opened 09:00; RCPond note 10:00 (1h); System auto-close 12:00 (final note = resolution).
    ticket = _ticket("RES0000001", work_notes=_RCPOND, comments=_SYSTEM, state="Closed")

    [m] = compute_metrics([ticket])

    assert m.time_to_first_rcpond == DurationStats(1, 0.04, 0.04, 0.04, 0.04)  ## 1h
    assert m.time_to_resolution == DurationStats(1, 0.12, 0.12, 0.12, 0.12)  ## 3h
    assert m.time_first_rcpond_to_resolution == DurationStats(1, 0.08, 0.08, 0.08, 0.08)  ## 2h
    ## System note is not a manual interaction, so there is no manual interval.
    assert m.time_to_first_manual is None


def test_compute_metrics_open_ticket_has_no_resolution_intervals():
    ticket = _ticket("RES0000001", work_notes=_RCPOND, state="New")

    [m] = compute_metrics([ticket])

    assert m.time_to_first_rcpond is not None  ## creation-relative intervals still computable
    assert m.time_to_resolution is None
    assert m.time_first_rcpond_to_resolution is None


## ── render_markdown ─────────────────────────────────────────────────────────


def test_render_markdown_empty():
    out = render_markdown([])
    assert "_No tickets found._" in out
    assert out.endswith("\n")


def test_render_markdown_single_type_has_no_aggregate_row():
    out = render_markdown([_make_metrics()])
    assert "| compute_allocation_request | 5 | 3 | 1 | 1 |" in out
    ## A single type needs no aggregate row (it would just duplicate the one row).
    assert "aggregate" not in out.lower()


def test_render_markdown_multiple_types_appends_labelled_aggregate():
    metrics = [
        _make_metrics(
            type_key="compute_allocation_request",
            total_tickets=5,
            rcpond_processed=3,
            manually_processed=1,
            rcpond_with_subsequent_manual=1,
        ),
        _make_metrics(
            type_key="github_org_membership",
            total_tickets=4,
            rcpond_processed=2,
            manually_processed=2,
            rcpond_with_subsequent_manual=0,
        ),
    ]
    out = render_markdown(metrics)
    assert "| compute_allocation_request | 5 | 3 | 1 | 1 |" in out
    assert "| github_org_membership | 4 | 2 | 2 | 0 |" in out
    ## Aggregate row sums each column across types and is clearly labelled.
    assert "| **All types (aggregate)** | 9 | 5 | 3 | 1 |" in out


def test_render_markdown_includes_interaction_distribution():
    out = render_markdown([_make_metrics()])
    assert "## Interaction distributions" in out
    ## Rows merge the RCPond and manual distributions by interaction count.
    assert "| 0 | 2 | 1 |" in out
    assert "| 1 | 3 | 4 |" in out


def test_render_markdown_includes_time_intervals_with_dash_for_missing():
    out = render_markdown([_make_metrics()])
    assert "## Time intervals (days)" in out
    assert "| Creation → first RCPond | 3 | 0.04 | 0.05 | 0.01 | 0.1 |" in out
    ## time_to_first_manual is None in the default metrics → em-dash placeholders.
    assert "| Creation → first manual | 0 | — | — | — | — |" in out


## ── command.analytics wiring ────────────────────────────────────────────────


def test_command_analytics_fetches_all_states_prints_and_returns_markdown(capsys):
    tickets = [_ticket("RES0000001", work_notes=_RCPOND), _ticket("RES0000002", work_notes=_HUMAN)]
    with patch("rcpond.command.ServiceNow") as MockSN:
        MockSN.return_value.get_tickets.return_value = tickets
        out = command.analytics(config=MagicMock())

    ## Analytics must consider every state, including closed/resolved/cancelled.
    MockSN.return_value.get_tickets.assert_called_once_with(state=TicketState.all_including_closed)
    ## The report is both returned and written verbatim to stdout.
    assert "# RCPond analytics report" in out
    assert "| compute_allocation_request | 2 | 1 | 1 | 0 |" in out
    assert out == capsys.readouterr().out

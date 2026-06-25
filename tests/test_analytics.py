from unittest.mock import MagicMock, patch

from rcpond import command, servicenow
from rcpond.analytics import TicketTypeMetrics, compute_stage1_metrics, render_markdown
from rcpond.servicenow import Ticket, TicketState

## short_description that matches ComputeAllocationRequestTicket.MATCH_CRITERIA
_CART_DESC = "Request access to HPC and cloud computing facilities"


def _note(ts: str, user: str, content: str, note_type: str = "Work notes") -> str:
    return f"{ts} - {user} ({note_type})\n{content}"


_RCPOND = _note("01/01/2026 10:00:00", "RCPond", servicenow._note_prefix("post_freeform_note") + "Response")
_HUMAN = _note("01/01/2026 11:00:00", "Alice", "A human work note")
_SYSTEM = _note("01/01/2026 12:00:00", "System", "Automatically closed.", note_type="Additional comments")


def _ticket(number: str, *, work_notes: str = "", comments: str = "", short_description: str = _CART_DESC) -> Ticket:
    return Ticket(
        sys_id=number,
        number=number,
        opened_at="01/01/2026 09:00:00",
        requested_for="",
        u_category="",
        u_sub_category="",
        short_description=short_description,
        state="New",
        assigned_to="",
        work_notes=work_notes,
        comments=comments,
    )


def test_compute_stage1_metrics_empty():
    assert compute_stage1_metrics([]) == []


def test_compute_stage1_metrics_skips_unknown_type():
    """Tickets whose short_description matches no registered type are excluded entirely."""
    unknown = _ticket("RES0000001", work_notes=_RCPOND, short_description="Some other request")
    assert compute_stage1_metrics([unknown]) == []


def test_compute_stage1_metrics_counts():
    tickets = [
        _ticket("RES0000001", work_notes=_RCPOND),  ## RCPond only
        _ticket("RES0000002", work_notes=_HUMAN),  ## manual only
        _ticket("RES0000003", work_notes="\n".join([_RCPOND, _HUMAN])),  ## RCPond + subsequent manual
        _ticket("RES0000004"),  ## no notes: neither RCPond nor manual
        _ticket("RES0000005", work_notes=_RCPOND, comments=_SYSTEM),  ## RCPond + System (automated, not manual)
    ]

    result = compute_stage1_metrics(tickets)

    assert result == [
        TicketTypeMetrics(
            type_key="compute_allocation_request",
            total_tickets=5,
            rcpond_processed=3,  ## tickets 1, 3, 5
            manually_processed=1,  ## ticket 2 (4 has no notes; 5 has RCPond)
            rcpond_with_subsequent_manual=1,  ## ticket 3 only (5's System note is not manual)
        )
    ]


## ── render_markdown ─────────────────────────────────────────────────────────


def test_render_markdown_empty():
    out = render_markdown([])
    assert "_No tickets found._" in out
    assert out.endswith("\n")


def test_render_markdown_single_type_has_no_aggregate_row():
    metrics = [TicketTypeMetrics("compute_allocation_request", 5, 3, 1, 1)]
    out = render_markdown(metrics)
    assert "| compute_allocation_request | 5 | 3 | 1 | 1 |" in out
    ## A single type needs no aggregate row (it would just duplicate the one row).
    assert "aggregate" not in out.lower()


def test_render_markdown_multiple_types_appends_labelled_aggregate():
    metrics = [
        TicketTypeMetrics("compute_allocation_request", 5, 3, 1, 1),
        TicketTypeMetrics("github_org_membership", 4, 2, 2, 0),
    ]
    out = render_markdown(metrics)
    assert "| compute_allocation_request | 5 | 3 | 1 | 1 |" in out
    assert "| github_org_membership | 4 | 2 | 2 | 0 |" in out
    ## Aggregate row sums each column across types and is clearly labelled.
    assert "| **All types (aggregate)** | 9 | 5 | 3 | 1 |" in out


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

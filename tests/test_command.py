"""Tests for the long_list behaviour of each command.

Each command has a specific policy:

- display_all_tickets:      honours an explicit long_list argument
- display_single_ticket:    uses get_ticket(), which always searches all tickets
- process_next_ticket:      only ever selects from unassigned tickets
- process_specific_ticket:  uses get_ticket(), which always searches all tickets
- batch_process_tickets:    only ever processes unassigned tickets
"""

from unittest.mock import MagicMock, patch

import pytest

from rcpond import command
from rcpond.config import Config
from rcpond.servicenow import Ticket


@pytest.fixture()
def cfg():
    return MagicMock(spec=Config)


@pytest.fixture()
def ticket():
    return Ticket(
        sys_id="abc123",
        number="RES0001000",
        opened_at="01/01/2026 09:00:00",
        requested_for="Test User",
        u_category="HPC",
        u_sub_category="New",
        short_description="Request access to HPC and cloud computing facilities",
        state="New",
        assigned_to="",
        work_notes="",
        comments="",
    )


## ── display_all_tickets ─────────────────────────────────────────────────────


def test_display_all_tickets_uses_shortlist_by_default(cfg):
    """display_all_tickets passes long_list=False by default."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(long_list=False, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(long_list=False)


def test_display_all_tickets_can_use_longlist(cfg):
    """display_all_tickets passes long_list=True when requested."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(long_list=True, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(long_list=True)


## ── display_single_ticket ───────────────────────────────────────────────────


def test_display_single_ticket_uses_get_ticket(cfg, ticket):
    """display_single_ticket delegates lookup to get_ticket(), which searches all tickets."""
    with patch("rcpond.command.ServiceNow") as MockSN, patch("rcpond.command.display_full_ticket"):
        MockSN.return_value.get_ticket.return_value = ticket
        command.display_single_ticket(ticket_number="RES0001000", config=cfg)
    MockSN.return_value.get_ticket.assert_called_once_with("RES0001000")

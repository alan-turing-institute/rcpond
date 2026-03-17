"""Tests for the include_assigned_tickets behaviour of each command.

Each command has a specific policy:

- display_all_tickets:      honours an explicit include_assigned_tickets argument
- display_single_ticket:    uses get_ticket(), which always searches all tickets
- process_next_ticket:      only ever selects from unassigned tickets
- process_specific_ticket:  uses get_ticket(), which always searches all tickets
- batch_process_tickets:    only ever processes unassigned tickets
"""

from unittest.mock import MagicMock, patch

import pytest

from rcpond import command
from rcpond.config import Config
from rcpond.servicenow import FullTicket, Ticket


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
    )


## ── display_all_tickets ─────────────────────────────────────────────────────


def test_display_all_tickets_excludes_assigned_by_default(cfg):
    """display_all_tickets passes include_assigned_tickets=False by default."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(include_assigned_tickets=False, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(include_assigned_tickets=False)


def test_display_all_tickets_can_include_assigned(cfg):
    """display_all_tickets passes include_assigned_tickets=True when requested."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(include_assigned_tickets=True, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(include_assigned_tickets=True)


## ── display_single_ticket ───────────────────────────────────────────────────


def test_display_single_ticket_uses_get_ticket(cfg, ticket):
    """display_single_ticket delegates lookup to get_ticket(), which searches all tickets."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        MockSN.return_value.get_ticket.return_value = ticket
        MockSN.return_value.get_full_ticket.return_value = MagicMock(spec=FullTicket)
        command.display_single_ticket(ticket_number="RES0001000", config=cfg)
    MockSN.return_value.get_ticket.assert_called_once_with("RES0001000")

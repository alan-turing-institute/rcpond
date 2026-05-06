import base64
import json
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from rcpond import config, servicenow
from rcpond.servicenow import NoteEntry, ServiceNow, Ticket


def _make_jwt(sub: str) -> str:
    """Build a minimal JWT with the given sub claim (no real signature)."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fake-sig"


@pytest.fixture()
def dev_instance_config(monkeypatch, tmp_path) -> config.Config:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return config.Config(".env")


@pytest.fixture()
def dev_instance_sn(dev_instance_config) -> servicenow.ServiceNow:
    return servicenow.ServiceNow(dev_instance_config)


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
    )


@pytest.fixture()
def sn_instance():
    """A ServiceNow instance with the HTTP session replaced by a MagicMock."""
    sn = ServiceNow.__new__(ServiceNow)
    sn._base_url = "https://example.com/api/now/table"
    sn._web_base_url = "https://example.com"
    sn.session = MagicMock()
    return sn


def test_web_url_returns_correct_url(sn_instance, ticket):
    url = sn_instance.web_url(ticket)
    assert url == f"https://example.com/x_tati_resmgt_research.do?sys_id={ticket.sys_id}"


def test_web_url_strips_trailing_slash(sn_instance, ticket):
    sn_instance._web_base_url = "https://example.com/"
    url = sn_instance.web_url(ticket)
    assert "example.com//" not in url


## ── assign_to_me ────────────────────────────────────────────────────────────


def test_assign_to_me_raises_without_oauth(sn_instance, ticket):
    """Static token auth must raise NotImplementedError with a helpful message."""
    sn_instance._is_oauth = False
    with pytest.raises(NotImplementedError, match="OAuth"):
        sn_instance.assign_to_me(ticket)


def test_assign_to_me_calls_assign_to_with_current_user(sn_instance, ticket):
    """With OAuth, assign_to_me decodes the JWT sub and calls assign_to."""
    sn_instance._is_oauth = True
    sn_instance.session.headers = {"Authorization": f"Bearer {_make_jwt('user-sys-id-123')}"}
    with patch.object(sn_instance, "assign_to") as mock_assign:
        sn_instance.assign_to_me(ticket)
    mock_assign.assert_called_once_with(ticket, "user-sys-id-123")


def test_current_user_sys_id_decodes_jwt(sn_instance):
    """_current_user_sys_id extracts the sub claim from the bearer token."""
    sn_instance.session.headers = {"Authorization": f"Bearer {_make_jwt('abc-xyz-456')}"}
    assert sn_instance._current_user_sys_id() == "abc-xyz-456"


def test_ticket_assign_to_me_delegates_to_service_now(ticket):
    """Ticket.assign_to_me delegates to service_now.assign_to_me."""
    sn = MagicMock(spec=ServiceNow)
    ticket.assign_to_me(sn)
    sn.assign_to_me.assert_called_once_with(ticket)


def test_assign_to_valid_assignee(sn_instance, ticket):
    """When ServiceNow recognises the assignee, the new assignee dict is returned.
    (Makes assumptions about the internal working of `assign_to`)
    """
    original = {"display_value": "Alice Smith", "value": "orig-sys-id"}
    new = {"display_value": "Bob Jones", "value": "bob-sys-id"}

    with (
        patch.object(sn_instance, "get_assignee", side_effect=[original, new]),
        patch.object(sn_instance, "_attempt_assign_to") as mock_attempt,
    ):
        result = sn_instance.assign_to(ticket, "bob@example.com")

    assert result == new
    mock_attempt.assert_called_once_with(ticket, "bob@example.com")


def test_assign_to_invalid_assignee_reverts(sn_instance, ticket):
    """When ServiceNow does not recognise the assignee, the ticket is reverted and ValueError raised.
    (Makes assumptions about the internal working of `assign_to`)
    """
    original = {"display_value": "Alice Smith", "value": "orig-sys-id"}
    not_recognised = {"display_value": "", "value": ""}

    with (
        patch.object(sn_instance, "get_assignee", side_effect=[original, not_recognised]),
        patch.object(sn_instance, "_attempt_assign_to") as mock_attempt,
        pytest.raises(ValueError, match="nobody@example.com"),
    ):
        sn_instance.assign_to(ticket, "nobody@example.com")

    assert mock_attempt.call_args_list == [
        call(ticket, "nobody@example.com"),
        call(ticket, "orig-sys-id"),
    ]


def test_assign_to_empty_string_unassigns(sn_instance, ticket):
    """Passing assignee='' unassigns the ticket and returns the empty assignee dict.
    (Makes assumptions about the internal working of `assign_to`)
    """
    original = {"display_value": "Alice Smith", "value": "orig-sys-id"}
    unassigned = {"display_value": "", "value": ""}

    with (
        patch.object(sn_instance, "get_assignee", side_effect=[original, unassigned]),
        patch.object(sn_instance, "_attempt_assign_to") as mock_attempt,
    ):
        result = sn_instance.assign_to(ticket, "")

    assert result == unassigned
    mock_attempt.assert_called_once_with(ticket, "")


def test_parse_comment_display_values():
    input = (
        "11/03/2026 13:32:41 - Research API User (Work notes)\n"
        "A multiline \n"
        "work note\n"
        "\n"
        "11/03/2026 11:18:09 - Joe Bloggs (Work notes)\n"
        "[code]<p>Manually added work note.</p>[/code]\n"
        "\n"
        "11/03/2026 11:00:20 - Research API User (Work notes)\n"
        "A work note\n"
        "\n"
    )

    expected_output = [
        NoteEntry(datetime(2026, 3, 11, 13, 32, 41), "Research API User", "Work notes", "A multiline \nwork note"),
        NoteEntry(
            datetime(2026, 3, 11, 11, 18, 9),
            "Joe Bloggs",
            "Work notes",
            "[code]<p>Manually added work note.</p>[/code]",
        ),
        NoteEntry(datetime(2026, 3, 11, 11, 0, 20), "Research API User", "Work notes", "A work note"),
    ]

    actual_output = servicenow._parse_comment_display_values(input)

    assert actual_output == expected_output


@pytest.mark.integration()
def test_post_note(dev_instance_sn):
    tickets = dev_instance_sn.get_tickets()

    # get first alphanumeric ticket number
    first_num = min([t.number for t in tickets])
    my_tkt = [t for t in tickets if t.number == first_num].pop()
    print(my_tkt)
    print()

    before_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    dev_instance_sn.post_note(my_tkt, "Test Work note A")
    dev_instance_sn.post_note(my_tkt, "Test Work note B")

    after_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    assert after_work_note_count == before_work_note_count + 2


@pytest.mark.integration()
def test_get_tickets(dev_instance_sn):
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(include_assigned_tickets=True)

    assert len(all_tickets) >= len(unassigned_tickets)


@pytest.mark.integration()
def test_change_assignee(dev_instance_sn):
    # Attempt to select one assigned and on unassigned ticket
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(include_assigned_tickets=True)

    unassigned_sys_ids = {t.sys_id for t in unassigned_tickets}
    assigned_tickets = [t for t in all_tickets if t.sys_id not in unassigned_sys_ids]

    # Check that this is at least one of each:
    assert unassigned_tickets, "No unassigned tickets available to test with"
    assert assigned_tickets, "No assigned tickets available to identify a valid user"

    unassigned_ticket = unassigned_tickets[0]
    # Get the assignee of the assigned ticket.
    ## We explictly assume that this assignee is value, though it is not actually guaranteed by the ServiceNow API
    assignee_sys_id = dev_instance_sn.get_assignee(assigned_tickets[0])["value"]

    ## Assign the previously unassigned ticket
    dev_instance_sn.assign_to(unassigned_ticket, assignee_sys_id)

    ## Check that the number of assigned and unassigned tickets has changed as expected
    after_assignment = dev_instance_sn.get_tickets()
    assert len(after_assignment) == len(unassigned_tickets) - 1

    ## Reset: unassign the ticket
    dev_instance_sn.assign_to(unassigned_ticket, "")

    ## Check that the number of assigned and unassigned tickets has reverted as expected
    after_reset = dev_instance_sn.get_tickets()
    assert len(after_reset) == len(unassigned_tickets)

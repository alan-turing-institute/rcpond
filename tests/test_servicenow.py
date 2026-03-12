from datetime import datetime
from pprint import pprint
from unittest.mock import MagicMock, call, patch

import pytest

from rcpond import config, servicenow
from rcpond.servicenow import ServiceNow, Ticket


@pytest.fixture()
def dev_instance_config() -> config.Config:
    return config.Config(".env")


@pytest.fixture()
def dev_instance_sn(dev_instance_config) -> servicenow.ServiceNow:
    return servicenow.ServiceNow(dev_instance_config)


@pytest.mark.integration()
def test_get_tickets(dev_instance_sn):
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(include_assigned_tickets=True)

    assert len(all_tickets) >= len(unassigned_tickets)


@pytest.mark.integration()
def test_get_assignee(dev_instance_sn):
    tickets = dev_instance_sn.get_unassigned_tickets()

    my_tkt = [t for t in tickets if t.number == "RES0001345"].pop()
    print(my_tkt)
    print()

    dev_instance_sn.assign_to(my_tkt, "my.user.name@turing.ac.uk")
    print(dev_instance_sn.get_assignee(my_tkt))

    with pytest.raises(ValueError, match="real.person"):
        dev_instance_sn.assign_to(my_tkt, "real.person@turing.ac.uk")
        dev_instance_sn.get_assignee(my_tkt)

    dev_instance_sn.assign_to(my_tkt, "")
    print(dev_instance_sn.get_assignee(my_tkt))

    dev_instance_sn.assign_to(my_tkt, "my_user_sys_id_as_str")
    print(dev_instance_sn.get_assignee(my_tkt))

    pytest.fail("WIP")


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


@pytest.fixture()
def sn_instance():
    """A ServiceNow instance with the HTTP session replaced by a MagicMock."""
    sn = ServiceNow.__new__(ServiceNow)
    sn._base_url = "https://example.com/api/now/table"
    sn.session = MagicMock()
    return sn


def test_assign_to_valid_assignee(sn_instance, ticket):
    """When ServiceNow recognises the assignee, the new assignee dict is returned.
    (Makes assumptions about the internal working of `assign_to`)
    """
    original = {"display_value": "Alice Smith", "value": "orig-sys-id"}
    new = {"display_value": "Bob Jones", "value": "bob-sys-id"}

    with patch.object(sn_instance, "get_assignee", side_effect=[original, new]):
        with patch.object(sn_instance, "_attempt_assign_to") as mock_attempt:
            result = sn_instance.assign_to(ticket, "bob@example.com")

    assert result == new
    mock_attempt.assert_called_once_with(ticket, "bob@example.com")


def test_assign_to_invalid_assignee_reverts(sn_instance, ticket):
    """When ServiceNow does not recognise the assignee, the ticket is reverted and ValueError raised.
    (Makes assumptions about the internal working of `assign_to`)
    """
    original = {"display_value": "Alice Smith", "value": "orig-sys-id"}
    not_recognised = {"display_value": "", "value": ""}

    with patch.object(sn_instance, "get_assignee", side_effect=[original, not_recognised]):
        with patch.object(sn_instance, "_attempt_assign_to") as mock_attempt:
            with pytest.raises(ValueError, match="nobody@example.com"):
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

    with patch.object(sn_instance, "get_assignee", side_effect=[original, unassigned]):
        with patch.object(sn_instance, "_attempt_assign_to") as mock_attempt:
            result = sn_instance.assign_to(ticket, "")

    assert result == unassigned
    mock_attempt.assert_called_once_with(ticket, "")


@pytest.mark.integration()
def test_assign_to_old(dev_instance_sn):
    tickets = dev_instance_sn.get_unassigned_tickets()

    [print(t.number) for t in tickets]

    my_tkt = [t for t in tickets if t.number == "RES0001345"].pop()
    print(my_tkt)
    print()

    full_tkt = dev_instance_sn.get_full_ticket(my_tkt)
    print(full_tkt)

    dev_instance_sn.assign_to(my_tkt, "real.person@turing.ac.uk")
    dev_instance_sn.assign_to(my_tkt, "someone.who.never.existed.fake@turing.ac.uk")
    dev_instance_sn.assign_to(my_tkt, "someone.who.never.existed.fake@example.com")
    dev_instance_sn.assign_to(my_tkt, "")
    dev_instance_sn.assign_to(my_tkt, "sam@example.com")
    dev_instance_sn.assign_to(my_tkt, "not_a_email_address")
    dev_instance_sn.assign_to(my_tkt, None)

    pytest.fail("WIP")


@pytest.mark.integration()
def test_post_note(dev_instance_sn):
    tickets = dev_instance_sn.get_tickets()

    # get first alphanumeric ticket number
    first_num = min([t.number for t in tickets])
    my_tkt = [t for t in tickets if t.number == first_num].pop()
    print(my_tkt)
    print()

    # full_tkt = dev_instance_sn.get_full_ticket(my_tkt)
    # print(full_tkt)
    before_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    dev_instance_sn.post_note(my_tkt, "Test Work note A")
    dev_instance_sn.post_note(my_tkt, "Test Work note B")

    after_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    assert after_work_note_count == before_work_note_count + 2


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
        ("11/03/2026 13:32:41 - Research API User (Work notes)\n" "A multiline \n" "work note"),
        ("11/03/2026 11:18:09 - Joe Bloggs (Work notes)\n" "[code]<p>Manually added work note.</p>[/code]"),
        ("11/03/2026 11:00:20 - Research API User (Work notes)\n" "A work note"),
    ]

    actual_output = servicenow._parse_comment_display_values(input)
    pprint(actual_output)

    assert len(actual_output) == 3
    assert actual_output == expected_output

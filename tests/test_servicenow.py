from datetime import datetime
from pprint import pprint

import pytest

from rcpond import config, servicenow


@pytest.fixture()
def dev_instance_config() -> config.Config:
    return config.Config(".env")


@pytest.fixture()
def dev_instance_sn(dev_instance_config) -> servicenow.ServiceNow:
    return servicenow.ServiceNow(dev_instance_config)


def test_servicenow_dev_instance(dev_instance_sn):
    tickets = dev_instance_sn.get_unassigned_tickets()

    for tkt in tickets:
        print(tkt)
        print()

    pytest.fail("WIP")


def test_get_current_user_sys_id(dev_instance_sn):
    actual_user = dev_instance_sn.get_current_user_sys_id()
    print(actual_user)

    pytest.fail("WIP")


def test_assign_to(dev_instance_sn):
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

    pytest.fail("WIP")


def test_post_note(dev_instance_sn):
    tickets = dev_instance_sn.get_unassigned_tickets()

    my_tkt = [t for t in tickets if t.number == "RES0001192"].pop()
    print(my_tkt)
    print()

    # full_tkt = dev_instance_sn.get_full_ticket(my_tkt)
    # print(full_tkt)

    dev_instance_sn.post_note(my_tkt, f"A multiline work note\nat: {datetime.now().isoformat(timespec='seconds')}")

    pytest.fail("WIP")


def test_get_work_notes(dev_instance_sn):
    tickets = dev_instance_sn.get_unassigned_tickets()

    my_tkt = [t for t in tickets if t.number == "RES0001192"].pop()
    print(my_tkt)
    print()

    actual_notes = dev_instance_sn.get_work_notes(my_tkt)
    print(type(actual_notes))

    pprint(actual_notes)

    pytest.fail("WIP")


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

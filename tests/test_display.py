"""Tests for rcpond.display."""

import io

import pytest
from rich.console import Console

from rcpond.display import (
    display_compute_allocation_request_ticket,
    display_github_leavers_request_ticket,
    display_github_onboarding_request_ticket,
)
from rcpond.servicenow import (
    ComputeAllocationRequestTicket,
    GitHubOnboardingRequestTicket,
    ResearchLeaversGitHubTicket,
    Ticket,
)


@pytest.fixture()
def full_ticket() -> ComputeAllocationRequestTicket:
    base = Ticket(
        sys_id="abc123",
        number="RES0001000",
        opened_at="01/01/2026 09:00:00",
        requested_for="Jane Bloggs",
        u_category="Research Services",
        u_sub_category="Research Computing Services",
        short_description="Request access to HPC and cloud computing facilities",
        state="New",
        assigned_to="",
        work_notes="",
        comments="",
    )
    return ComputeAllocationRequestTicket.from_Ticket(
        base,
        work_notes="01/01/2026 09:30:00 - RCP Team (Work notes)\nTicket received.",
        comments="",
        project_title="Climate Modelling",
        research_area_programme="Environmental Science",
        if_other_please_specify="",
        pi_supervisor_name="Prof. A. Smith",
        pi_supervisor_email="a.smith@example.ac.uk",
        which_service="Azure",
        subscription_type="Project",
        which_finance_code="ENV-2026-01",
        pmu_contact_email="pmu@example.ac.uk",
        credits_requested="5000",
        which_facility="",
        if_other_please_specify_facility="",
        cpu_hours_required="",
        gpu_hours_required="100",
        new_or_existing_allocation="New",
        azure_subscription_id_or_hpc_group_project_id="sub-abc-123",
        start_date="01/02/2026",
        end_date="31/01/2027",
        data_sensitivity="Personal",
        platform_justification="Azure GPU instances required for model training.",
        research_justification="High-resolution climate simulations require significant compute.",
        computational_requirements="V100 GPUs, 100 GPU hours.",
        users_who_require_access_names_and_emails="jane.bloggs@example.ac.uk",
        cost_compute_time_breakdown="£500/month for 10 months.",
    )


def _capture(ticket: ComputeAllocationRequestTicket) -> str:
    """Run display_full_ticket and return the plain-text output."""
    buf = io.StringIO()
    con = Console(file=buf, highlight=False, no_color=True)
    display_compute_allocation_request_ticket(ticket, console=con)
    return buf.getvalue()


def test_display_full_ticket_contains_number(full_ticket):
    assert "RES0001000" in _capture(full_ticket)


def test_display_full_ticket_contains_requestor(full_ticket):
    assert "Jane Bloggs" in _capture(full_ticket)


def test_display_full_ticket_contains_project_title(full_ticket):
    assert "Climate Modelling" in _capture(full_ticket)


def test_display_full_ticket_contains_service(full_ticket):
    assert "Azure" in _capture(full_ticket)


def test_display_full_ticket_contains_pi(full_ticket):
    assert "Prof. A. Smith" in _capture(full_ticket)


def test_display_full_ticket_contains_work_notes(full_ticket):
    assert "Ticket received." in _capture(full_ticket)


def test_display_full_ticket_empty_work_notes_omits_section(full_ticket):
    full_ticket.work_notes = ""
    output = _capture(full_ticket)
    assert "Work notes" not in output


def test_display_full_ticket_empty_users_omits_section(full_ticket):
    full_ticket.users_who_require_access_names_and_emails = ""
    output = _capture(full_ticket)
    assert "Users requiring access" not in output


## --------------------------------------------------------------------------------
## GitHub onboarding and leavers tickets


def _base_ticket(short_description: str, *, work_notes: str = "") -> Ticket:
    return Ticket(
        sys_id="abc123",
        number="RES0002000",
        opened_at="01/01/2026 09:00:00",
        requested_for="Jane Bloggs",
        u_category="Research Services",
        u_sub_category="Research Computing Services",
        short_description=short_description,
        state="New",
        assigned_to="",
        work_notes=work_notes,
        comments="",
    )


def _render(display_fn, ticket) -> str:
    """Render a ticket to plain text.

    A wide console keeps Rich from wrapping values mid-string, which would otherwise
    break the substring assertions for no reason connected to the code under test.
    """
    buf = io.StringIO()
    con = Console(file=buf, highlight=False, no_color=True, width=200)
    display_fn(ticket, console=con)
    return buf.getvalue()


@pytest.fixture()
def onboarding_ticket() -> GitHubOnboardingRequestTicket:
    return GitHubOnboardingRequestTicket.from_Ticket(
        _base_ticket(
            "Requesting Membership of Turing GitHub organisation",
            work_notes="01/01/2026 09:30:00 - RCP Team (Work notes)\nOnboarding note.",
        ),
        github_username="octo-newbie",
        person_to_be_added_to_github_organisation="Sam Newcomer",
        requested_by="Jane Bloggs",
        turing_email_address_of_the_person_being_added_to_the_github_organisation="sam.newcomer@turing.ac.uk",
        turing_email_address_of_the_person_making_the_request="jane.bloggs@turing.ac.uk",
    )


@pytest.fixture()
def leavers_ticket() -> ResearchLeaversGitHubTicket:
    return ResearchLeaversGitHubTicket.from_Ticket(
        _base_ticket(
            "Research Record for GitHub Admins through Leaver Process",
            work_notes="01/01/2026 09:30:00 - RCP Team (Work notes)\nLeaver note.",
        ),
        leaver_department="Research Engineering",
        leaver_email="alex.departing@turing.ac.uk",
        leaver_github_username="octo-leaver",
        leaver_leave_date="31/03/2026",
        leaver_title="Senior Research Engineer",
        research_leaver="Alex Departing",
    )


@pytest.mark.parametrize(
    "expected",
    [
        "RES0002000",
        "Sam Newcomer",
        "octo-newbie",
        "sam.newcomer@turing.ac.uk",
        "Jane Bloggs",
        "jane.bloggs@turing.ac.uk",
    ],
    ids=[
        "ticket_number",
        "person_added",
        "github_username",
        "person_added_email",
        "requested_by",
        "requester_email",
    ],
)
def test_display_onboarding_ticket_shows_every_field(onboarding_ticket, expected):
    """Each catalogue field must reach the output; a dropped one is easy not to notice."""
    assert expected in _render(display_github_onboarding_request_ticket, onboarding_ticket)


@pytest.mark.parametrize(
    "expected",
    [
        "RES0002000",
        "Alex Departing",
        "Senior Research Engineer",
        "Research Engineering",
        "alex.departing@turing.ac.uk",
        "octo-leaver",
        "31/03/2026",
    ],
    ids=[
        "ticket_number",
        "leaver_name",
        "leaver_title",
        "leaver_department",
        "leaver_email",
        "leaver_github_username",
        "leave_date",
    ],
)
def test_display_leavers_ticket_shows_every_field(leavers_ticket, expected):
    assert expected in _render(display_github_leavers_request_ticket, leavers_ticket)


@pytest.mark.parametrize(
    ("display_fn", "fixture_name", "note_text"),
    [
        (display_github_onboarding_request_ticket, "onboarding_ticket", "Onboarding note."),
        (display_github_leavers_request_ticket, "leavers_ticket", "Leaver note."),
    ],
    ids=["onboarding", "leavers"],
)
def test_display_shows_work_notes(request, display_fn, fixture_name, note_text):
    ticket = request.getfixturevalue(fixture_name)
    assert note_text in _render(display_fn, ticket)


@pytest.mark.parametrize(
    ("display_fn", "fixture_name"),
    [
        (display_github_onboarding_request_ticket, "onboarding_ticket"),
        (display_github_leavers_request_ticket, "leavers_ticket"),
    ],
    ids=["onboarding", "leavers"],
)
def test_display_empty_work_notes_omits_the_section(request, display_fn, fixture_name):
    ticket = request.getfixturevalue(fixture_name)
    ticket.work_notes = ""
    assert "Work notes" not in _render(display_fn, ticket)

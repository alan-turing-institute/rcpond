"""Tests for rcpond.display."""

import io

import pytest
from rich.console import Console

from rcpond.display import display_full_ticket
from rcpond.servicenow import FullTicket, Ticket


@pytest.fixture()
def full_ticket() -> FullTicket:
    base = Ticket(
        sys_id="abc123",
        number="RES0001000",
        opened_at="01/01/2026 09:00:00",
        requested_for="Jane Bloggs",
        u_category="Research Services",
        u_sub_category="Research Computing Services",
        short_description="Request access to HPC and cloud computing facilities",
        state="New",
    )
    return FullTicket.from_Ticket(
        base,
        work_notes="01/01/2026 09:30:00 - RCP Team (Work notes)\nTicket received.",
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


def _capture(ticket: FullTicket) -> str:
    """Run display_full_ticket and return the plain-text output."""
    buf = io.StringIO()
    con = Console(file=buf, highlight=False, no_color=True)
    display_full_ticket(ticket, console=con)
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

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rcpond.servicenow import FullTicket, ServiceNow, Ticket
from rcpond.tools import PostFreeformNoteTool, PostTemplatedNoteTool, get_available_tools

_WORKING_TEMPLATES_DIR = Path("tests/fixtures/working_templates")


def _make_config(email_templates_dir=_WORKING_TEMPLATES_DIR):
    config = MagicMock()
    config.email_templates_dir = email_templates_dir
    return config


# --- PostFreeformNoteTool ---


def test_post_freeform_note_schema():
    tool = PostFreeformNoteTool()
    result = tool.to_openai_dict()

    assert result["type"] == "function"
    assert result["function"]["name"] == "post_freeform_note"
    params = result["function"]["parameters"]
    assert params["properties"]["note"] == {"type": "string"}
    assert params["required"] == ["note"]


def test_post_freeform_note_execute():
    service_now = MagicMock()
    ticket = Ticket(
        sys_id="abc",
        number="RES001",
        opened_at="01/01/2025 09:00:00",
        requested_for="Alice",
        u_category="RC",
        u_sub_category="Azure",
        short_description="Request access",
        state="New",
        assigned_to="",
    )
    PostFreeformNoteTool().execute(service_now, ticket, note="Please provide more information.")
    service_now.post_note.assert_called_once_with(ticket, note="Please provide more information.")


# --- PostTemplatedNoteTool ---


def test_post_templated_note_schema_includes_template_enum():
    tool = PostTemplatedNoteTool(_make_config())
    result = tool.to_openai_dict()

    template_name_param = result["function"]["parameters"]["properties"]["template_name"]
    assert template_name_param["type"] == "string"
    assert "mock_working_template.yaml.j2" in template_name_param["enum"]


def test_post_templated_note_schema_includes_llm_vars():
    tool = PostTemplatedNoteTool(_make_config())
    result = tool.to_openai_dict()

    properties = result["function"]["parameters"]["properties"]
    ## working template has working_email_subject and working_email_body as LLM vars
    assert "working_email_subject" in properties
    assert "working_email_body" in properties
    ## ticket is context, not LLM-supplied
    assert "ticket" not in properties
    assert "template_name" in result["function"]["parameters"]["required"]


def test_post_templated_note_execute_renders_and_posts():
    service_now = MagicMock(spec=ServiceNow)
    ticket = FullTicket(
        sys_id="abc",
        number="RES001",
        opened_at="01/01/2025 09:00:00",
        requested_for="Alice",
        u_category="RC",
        u_sub_category="Azure",
        short_description="Request access",
        state="New",
        assigned_to="",
        work_notes="",
        comments="",
        project_title="",
        research_area_programme="",
        if_other_please_specify="",
        pi_supervisor_name="",
        pi_supervisor_email="",
        which_service="",
        subscription_type="",
        which_finance_code="",
        pmu_contact_email="",
        credits_requested="",
        which_facility="",
        if_other_please_specify_facility="",
        cpu_hours_required="",
        gpu_hours_required="",
        new_or_existing_allocation="",
        azure_subscription_id_or_hpc_group_project_id="",
        start_date="",
        end_date="",
        data_sensitivity="",
        platform_justification="",
        research_justification="",
        computational_requirements="",
        users_who_require_access_names_and_emails="",
        cost_compute_time_breakdown="",
    )

    PostTemplatedNoteTool(_make_config()).execute(
        service_now,
        ticket,
        template_name="mock_working_template.yaml.j2",
        working_email_subject="HPC access",
        working_email_body="been waiting",
    )

    service_now.post_note.assert_called_once()
    rendered = service_now.post_note.call_args[1]["note"]
    assert "HPC access" in rendered
    assert "been waiting" in rendered


# --- get_available_tools ---


def test_get_available_tools_returns_two_tools():
    tools = get_available_tools(_make_config())
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "post_freeform_note" in names
    assert "post_templated_note" in names


# --- unknown tool raises ---


def test_call_tool_unknown_tool_raises():
    from rcpond.command import _process_ticket
    from rcpond.llm import LLM, LLMResponse

    ticket = MagicMock()
    service_now = MagicMock()
    config = MagicMock()
    config.email_templates_dir = _WORKING_TEMPLATES_DIR
    llm = MagicMock(spec=LLM)
    llm.generate.return_value = LLMResponse(
        response_text="ok",
        planned_tool_call={"function": {"name": "nonexistent_tool", "arguments": {}}},
    )
    service_now.get_full_ticket.return_value = FullTicket(
        sys_id="abc",
        number="RES001",
        opened_at="01/01/2025 09:00:00",
        requested_for="Alice",
        u_category="RC",
        u_sub_category="Azure",
        short_description="Request access",
        state="New",
        assigned_to="",
        work_notes="",
        comments="",
        project_title="",
        research_area_programme="",
        if_other_please_specify="",
        pi_supervisor_name="",
        pi_supervisor_email="",
        which_service="",
        subscription_type="",
        which_finance_code="",
        pmu_contact_email="",
        credits_requested="",
        which_facility="",
        if_other_please_specify_facility="",
        cpu_hours_required="",
        gpu_hours_required="",
        new_or_existing_allocation="",
        azure_subscription_id_or_hpc_group_project_id="",
        start_date="",
        end_date="",
        data_sensitivity="",
        platform_justification="",
        research_justification="",
        computational_requirements="",
        users_who_require_access_names_and_emails="",
        cost_compute_time_breakdown="",
    )

    with pytest.raises(ValueError, match="nonexistent_tool"):
        _process_ticket(ticket, dry_run=False, config=config, service_now=service_now, llm=llm)

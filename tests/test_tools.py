from unittest.mock import MagicMock

import pytest

from rcpond.servicenow import ServiceNow, Ticket
from rcpond.tool import Tool
from rcpond.tools import get_available_tools

# --- Tool class ---


def test_tool_init():
    def demo_func(service_now: ServiceNow, ticket: Ticket, a: int, b: str) -> tuple[int, str]:  # noqa: ARG001
        """A demo function for testing"""
        return (a, b)

    tool = Tool(demo_func)

    assert tool.name == "demo_func"
    assert tool.description == "A demo function for testing"
    ## ServiceNow and Ticket params are context, not LLM-visible
    assert tool.parameters == {"a": int, "b": str}


def test_tool_to_openai_dict():
    def my_tool(service_now: ServiceNow, ticket: Ticket, note: str, count: int) -> None:  # noqa: ARG001
        """Does a thing."""

    tool = Tool(my_tool)
    result = tool.to_openai_dict()

    assert result["type"] == "function"
    assert result["function"]["name"] == "my_tool"
    assert result["function"]["description"] == "Does a thing."
    params = result["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["note"] == {"type": "string"}
    assert params["properties"]["count"] == {"type": "integer"}
    assert set(params["required"]) == {"note", "count"}


def test_tool_execute():
    impl = MagicMock()

    def my_tool(service_now: ServiceNow, ticket: Ticket, note: str) -> None:
        """Does a thing."""
        impl(service_now, ticket, note=note)

    tool = Tool(my_tool)
    service_now = MagicMock()
    ticket = MagicMock()

    tool.execute(service_now, ticket, note="hello")

    impl.assert_called_once_with(service_now, ticket, note="hello")


# --- get_available_tools ---


def test_get_available_tools_returns_one_tool():
    tools = get_available_tools()
    assert len(tools) == 1
    assert tools[0].name == "post_freeform_note"


def test_get_available_tools_post_note_schema():
    tools = get_available_tools()
    openai_dict = tools[0].to_openai_dict()
    params = openai_dict["function"]["parameters"]
    assert "note" in params["properties"]
    assert params["properties"]["note"] == {"type": "string"}


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
    )
    tools = get_available_tools()
    tools[0].execute(service_now, ticket, note="Please provide more information.")
    service_now.post_note.assert_called_once_with(ticket, note="Please provide more information.")


def test_call_tool_unknown_tool_raises():
    from rcpond.command import _process_ticket
    from rcpond.llm import LLM, LLMResponse
    from rcpond.servicenow import FullTicket

    ticket = MagicMock()
    service_now = MagicMock()
    config = MagicMock()
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
        work_notes="",
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

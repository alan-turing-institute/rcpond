import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rcpond.command import ReplyMode
from rcpond.servicenow import ComputeAllocationRequestTicket, RelatedTicketMatch, ServiceNow, Ticket
from rcpond.tools import (
    CombineTicketHistoryTool,
    PostFreeformNoteTool,
    PostTemplatedNoteTool,
    get_available_tools,
    verify_render_all_templates,
)


def _make_cart(**overrides) -> ComputeAllocationRequestTicket:
    """Build a ComputeAllocationRequestTicket with blank defaults, overriding named fields."""
    base = {
        "sys_id": "abc",
        "number": "RES001",
        "opened_at": "01/01/2025 09:00:00",
        "requested_for": "Alice",
        "u_category": "RC",
        "u_sub_category": "Azure",
        "short_description": "Request access",
        "state": "New",
        "assigned_to": "",
        "work_notes": "",
        "comments": "",
    }
    extra_fields = {f.name: "" for f in dataclasses.fields(ComputeAllocationRequestTicket) if f.name not in base}
    return ComputeAllocationRequestTicket(**{**base, **extra_fields, **overrides})


_MOCK_TEMPLATES_DIR = Path("tests/fixtures/mock_templates")

_WORKING_TEMPLATES_DIR = Path("tests/fixtures/working_templates")
_PREFIX_TEMPLATES_DIR = Path("tests/fixtures/prefix_templates")


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
        work_notes="",
        comments="",
    )
    PostFreeformNoteTool().execute(service_now, ticket, note="Please provide more information.")
    service_now.post_note.assert_called_once_with(
        ticket, note="Please provide more information.", tool_name="post_freeform_note"
    )


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
    ticket = ComputeAllocationRequestTicket(
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


# --- underscore-prefix template filtering ---


def test_underscore_prefix_template_excluded_from_schema():
    tool = PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR))
    result = tool.to_openai_dict()

    template_enum = result["function"]["parameters"]["properties"]["template_name"]["enum"]
    assert "mock_main_template.yaml.j2" in template_enum
    assert "_mock_partial.j2" not in template_enum


def test_underscore_prefix_template_vars_included_in_schema():
    tool = PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR))
    result = tool.to_openai_dict()

    properties = result["function"]["parameters"]["properties"]
    ## variable from _mock_partial.j2 must be surfaced so the LLM can supply it
    assert "partial_footer_text" in properties


def test_underscore_prefix_template_available_to_jinja_renderer():
    service_now = MagicMock(spec=ServiceNow)
    ticket = MagicMock(spec=ComputeAllocationRequestTicket)

    PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR)).execute(
        service_now,
        ticket,
        template_name="mock_main_template.yaml.j2",
        main_subject="Test Subject",
        partial_footer_text="Partial footer",
    )

    service_now.post_note.assert_called_once()
    rendered = service_now.post_note.call_args[1]["note"]
    assert "Test Subject" in rendered
    assert "I am included from the partial" in rendered  # hardcoded in partial template
    assert "Partial footer" in rendered


# --- underscore-prefix template filtering (multi-dot filename, e.g. _mock_partial.yaml.j2) ---


def test_underscore_prefix_multi_dot_template_excluded_from_schema():
    tool = PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR))
    result = tool.to_openai_dict()

    template_enum = result["function"]["parameters"]["properties"]["template_name"]["enum"]
    assert "mock_main_template_multi_dot.yaml.j2" in template_enum
    assert "_mock_partial.yaml.j2" not in template_enum


def test_underscore_prefix_multi_dot_template_vars_included_in_schema():
    tool = PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR))
    result = tool.to_openai_dict()

    properties = result["function"]["parameters"]["properties"]
    ## variable from _mock_partial.yaml.j2 must be surfaced so the LLM can supply it
    assert "partial_yaml_footer_text" in properties


def test_underscore_prefix_multi_dot_template_available_to_jinja_renderer():
    service_now = MagicMock(spec=ServiceNow)
    ticket = MagicMock(spec=ComputeAllocationRequestTicket)

    PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR)).execute(
        service_now,
        ticket,
        template_name="mock_main_template_multi_dot.yaml.j2",
        main_multi_dot_subject="Multi-dot Subject",
        partial_yaml_footer_text="Yaml partial footer",
    )

    service_now.post_note.assert_called_once()
    rendered = service_now.post_note.call_args[1]["note"]
    assert "Multi-dot Subject" in rendered
    assert "I am included from the yaml partial" in rendered  # hardcoded in _mock_partial.yaml.j2
    assert "Yaml partial footer" in rendered


# --- is_terminal ---


def test_post_freeform_note_is_terminal():
    assert PostFreeformNoteTool().is_terminal is True


def test_post_templated_note_is_terminal():
    assert PostTemplatedNoteTool(_make_config()).is_terminal is True


# --- execute return type ---


def test_post_freeform_note_execute_returns_none():
    service_now = MagicMock()
    ticket = MagicMock(spec=Ticket)
    result = PostFreeformNoteTool().execute(service_now, ticket, note="Test note")
    assert result is None


def test_post_templated_note_execute_returns_none():
    service_now = MagicMock(spec=ServiceNow)
    ticket = MagicMock(spec=ComputeAllocationRequestTicket)
    result = PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR)).execute(
        service_now,
        ticket,
        template_name="mock_main_template.yaml.j2",
        main_subject="Subject",
        partial_footer_text="Footer",
    )
    assert result is None


# --- dry_run suppresses ServiceNow writes ---


def test_post_freeform_note_execute_dry_run_does_not_post():
    service_now = MagicMock()
    ticket = MagicMock(spec=Ticket)
    PostFreeformNoteTool().execute(service_now, ticket, dry_run=True, note="Test note")
    service_now.post_note.assert_not_called()


def test_post_templated_note_execute_dry_run_renders_but_does_not_post():
    service_now = MagicMock(spec=ServiceNow)
    ticket = MagicMock(spec=ComputeAllocationRequestTicket)
    PostTemplatedNoteTool(_make_config(_PREFIX_TEMPLATES_DIR)).execute(
        service_now,
        ticket,
        dry_run=True,
        template_name="mock_main_template.yaml.j2",
        main_subject="Subject",
        partial_footer_text="Footer",
    )
    service_now.post_note.assert_not_called()


# --- CombineTicketHistoryTool ---


def test_combine_ticket_history_is_not_terminal():
    assert CombineTicketHistoryTool().is_terminal is False


def test_combine_ticket_history_schema_takes_no_params():
    result = CombineTicketHistoryTool().to_openai_dict()
    assert result["function"]["name"] == "combine_ticket_history"
    params = result["function"]["parameters"]
    assert params["properties"] == {}
    assert params["required"] == []


def test_combine_ticket_history_execute_posts_audit_note_and_returns_history():
    source = _make_cart(number="RES0002000")
    related = _make_cart(
        number="RES0001000",
        state="Closed",
        opened_at="01/01/2024 09:00:00",
        project_title="Genome Project",
        work_notes="01/01/2024 10:00:00 - Jane Doe (Work notes)\nApproved last year.",
    )
    match = RelatedTicketMatch(ticket=related, matched_heuristics=("finance_code:TUR-2023-001",))

    service_now = MagicMock(spec=ServiceNow)
    service_now.find_related_tickets.return_value = [match]

    result = CombineTicketHistoryTool().execute(service_now, source)

    ## The combined history is posted as an audit note and also returned for the next LLM turn.
    service_now.post_note.assert_called_once()
    posted = service_now.post_note.call_args
    assert posted.args[0] is source
    assert posted.kwargs["tool_name"] == "combine_ticket_history"
    assert posted.kwargs["note"] == result

    assert "RES0001000" in result
    assert "Closed" in result
    assert "Genome Project" in result
    assert "finance_code:TUR-2023-001" in result
    assert "Approved last year." in result


def test_combine_ticket_history_execute_no_matches_does_not_post():
    source = _make_cart(number="RES0002000")
    service_now = MagicMock(spec=ServiceNow)
    service_now.find_related_tickets.return_value = []

    result = CombineTicketHistoryTool().execute(service_now, source)

    service_now.post_note.assert_not_called()
    assert "No related tickets" in result
    assert "RES0002000" in result


def test_combine_ticket_history_execute_dry_run_returns_history_without_posting():
    source = _make_cart(number="RES0002000")
    related = _make_cart(number="RES0001000", state="Closed", project_title="Genome Project")
    match = RelatedTicketMatch(ticket=related, matched_heuristics=("finance_code:TUR-2023-001",))

    service_now = MagicMock(spec=ServiceNow)
    service_now.find_related_tickets.return_value = [match]

    result = CombineTicketHistoryTool().execute(service_now, source, dry_run=True)

    ## Dry run still computes and returns the combined history, but writes nothing.
    service_now.post_note.assert_not_called()
    assert "RES0001000" in result


# --- verify_render_all_templates ---


def test_verify_render_all_templates_passes_for_valid_templates():
    results = verify_render_all_templates(_make_config())
    assert all(passed for _, passed, _ in results)
    assert any(name == "mock_working_template.yaml.j2" for name, _, _ in results)


def test_verify_render_all_templates_fails_for_malformed_template():
    results = verify_render_all_templates(_make_config(_MOCK_TEMPLATES_DIR))
    failed = [name for name, passed, _ in results if not passed]
    assert "mock_malformed_template.yaml.j2" in failed


def test_verify_render_all_templates_resolves_includes():
    ## Templates with {% include %} directives should render successfully
    results = verify_render_all_templates(_make_config(_PREFIX_TEMPLATES_DIR))
    assert all(passed for _, passed, _ in results)


def test_verify_render_all_templates_excludes_partials_from_results():
    results = verify_render_all_templates(_make_config(_PREFIX_TEMPLATES_DIR))
    names = [name for name, _, _ in results]
    assert "_mock_partial.j2" not in names
    assert "_mock_partial.yaml.j2" not in names


def test_verify_render_all_templates_uses_placeholder_suffix(tmp_path):
    ## render_all fills variables as <name>_placeholder; confirm via _render directly
    (tmp_path / "test.yaml.j2").write_text("subject: {{ email_subject }}")
    results = verify_render_all_templates(_make_config(tmp_path))
    assert results == [("test.yaml.j2", True, "")]
    rendered = PostTemplatedNoteTool(_make_config(tmp_path))._render(
        "test.yaml.j2", email_subject="email_subject_placeholder"
    )
    assert "email_subject_placeholder" in rendered


# --- get_available_tools ---


def test_get_available_tools_returns_all_tools():
    tools = get_available_tools(_make_config())
    names = [t.name for t in tools]
    assert "post_freeform_note" in names
    assert "post_templated_note" in names
    assert "combine_ticket_history" in names


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
    service_now.get_full_ticket.return_value = ComputeAllocationRequestTicket(
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
        _process_ticket(
            ticket, dry_run=False, config=config, service_now=service_now, llm=llm, reply_mode=ReplyMode.default
        )

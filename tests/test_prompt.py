import json
from pathlib import Path

import pytest

from rcpond.config import Config
from rcpond.prompt import construct_prompt
from rcpond.servicenow import FullTicket

_WORKING_TEMPLATES_DIR = Path("tests/fixtures/working_templates")

# --- Fixtures ---


@pytest.fixture()
def rules_text():
    return "Rule 1: Be helpful.\nRule 2: Be concise."


@pytest.fixture()
def template_text():
    return "You are an assistant.\n\nRules:\n{rules}\n\nProcess the submission."


@pytest.fixture()
def config(tmp_path, rules_text, template_text):
    rules = tmp_path / "RULES.md"
    rules.write_text(rules_text)
    template = tmp_path / "system_prompt_template.txt"
    template.write_text(template_text)
    email_templates = _WORKING_TEMPLATES_DIR
    return Config(
        cli_args={
            "llm_chat_completions_url": "https://api.example.com",
            "llm_api_key": "test-key",
            "llm_model": "gpt-4",
            "servicenow_token": "sn-token",
            "servicenow_url": "https://snow.example.com",
            "servicenow_oauth_scope": "useraccount",
            "servicenow_oauth_redirect_port": "8765",
            "servicenow_oauth_auth_url": "https://alanturingdev.service-now.com/oauth_auth.do",
            "servicenow_oauth_token_url": "https://alanturingdev.service-now.com/oauth_token.do",
            "rules_path": str(rules),
            "system_prompt_template_path": str(template),
            "email_templates_dir": str(email_templates),
        }
    )


@pytest.fixture()
def full_ticket():
    return FullTicket(
        sys_id="abc123",
        number="RES0001234",
        opened_at="01/01/2025 09:00:00",
        requested_for="Alice Example",
        u_category="Research Computing",
        u_sub_category="Azure",
        short_description="Request access to HPC and cloud computing facilities",
        state="New",
        assigned_to="",
        work_notes="",
        project_title="My Project",
        research_area_programme="Health",
        if_other_please_specify="",
        pi_supervisor_name="Dr. Smith",
        pi_supervisor_email="smith@example.com",
        which_service="Azure",
        subscription_type="Trial",
        which_finance_code="CORE",
        pmu_contact_email="",
        credits_requested="300",
        which_facility="",
        if_other_please_specify_facility="",
        cpu_hours_required="",
        gpu_hours_required="",
        new_or_existing_allocation="New",
        azure_subscription_id_or_hpc_group_project_id="",
        start_date="01/02/2025",
        end_date="01/08/2025",
        data_sensitivity="Public",
        platform_justification="Cloud is best for this workload.",
        research_justification="Aligns with Turing 2.0 priorities.",
        computational_requirements="2 VMs for 6 months.",
        users_who_require_access_names_and_emails="Alice Example alice@example.com",
        cost_compute_time_breakdown="2 VMs * 6 months = £300",
    )


# --- Tests ---


def test_construct_prompt_returns_strings(config, full_ticket):
    result = construct_prompt(full_ticket, config)
    assert isinstance(result, tuple)
    assert len(result) == 2
    system_prompt, user_prompt = result
    assert isinstance(system_prompt, str)
    assert isinstance(user_prompt, str)


def test_system_prompt_uses_template(config, full_ticket, template_text, rules_text):
    system_prompt, _ = construct_prompt(full_ticket, config)
    # Template text with {rules} replaced should equal the system prompt
    assert system_prompt == template_text.format(rules=rules_text).strip()


def test_user_prompt_is_valid_json(config, full_ticket):
    _, user_prompt = construct_prompt(full_ticket, config)
    parsed = json.loads(user_prompt)
    assert isinstance(parsed, dict)


def test_user_prompt_contains_ticket_fields(config, full_ticket):
    _, user_prompt = construct_prompt(full_ticket, config)
    parsed = json.loads(user_prompt)
    assert parsed["number"] == "RES0001234"
    assert parsed["project_title"] == "My Project"
    assert parsed["requested_for"] == "Alice Example"

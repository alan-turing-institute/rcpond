"""Tests for the ticket-state behaviour of each command.

Each command has a specific policy:

- display_all_tickets:      honours an explicit long_list argument
- display_single_ticket:    uses get_ticket(), which always searches all tickets
- process_next_ticket:      only ever selects from unassigned tickets
- process_specific_ticket:  uses get_ticket(), which always searches all tickets
- batch_process_tickets:    only ever processes unassigned tickets
"""

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rcpond import command
from rcpond.command import ReplyMode, _process_ticket
from rcpond.config import Config
from rcpond.llm import LLM, LLMResponse
from rcpond.servicenow import ComputeAllocationRequestTicket, Ticket, TicketState, _note_prefix

_WORKING_TEMPLATES_DIR = Path("tests/fixtures/working_templates")
_MOCK_TEMPLATES_DIR = Path("tests/fixtures/mock_templates")
_PREFIX_TEMPLATES_DIR = Path("tests/fixtures/prefix_templates")


def _make_template_config(email_templates_dir):
    config = MagicMock()
    config.email_templates_dir = email_templates_dir
    return config


@pytest.fixture(autouse=True)
def _isolated_xdg_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture()
def cfg(tmp_path):
    rules = tmp_path / "RULES.md"
    rules.write_text("Rule 1: Be helpful.")
    template = tmp_path / "system_prompt_template.txt"
    template.write_text("You are an assistant.\n\nRules:\n{rules}")
    return Config(
        cli_args={
            "llm_chat_completions_url": "https://api.example.com",
            "llm_api_key": "test-key",
            "llm_model": "gpt-4",
            "servicenow_token": "sn-token",
            "servicenow_url": "https://snow.example.com",
            "servicenow_web_url": "https://example.com",
            "rules_path": str(rules),
            "system_prompt_template_path": str(template),
            "email_templates_dir": str(_WORKING_TEMPLATES_DIR),
        }
    )


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
        work_notes="",
        comments="",
    )


## ── display_all_tickets ─────────────────────────────────────────────────────


def test_display_all_tickets_uses_user_focus_by_default(cfg):
    """display_all_tickets uses TicketState.user_focus when long_list=False."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(long_list=False, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(state=TicketState.user_focus)


def test_display_all_tickets_uses_all_open_for_longlist(cfg):
    """display_all_tickets uses TicketState.all_open when long_list=True."""
    with patch("rcpond.command.ServiceNow") as MockSN:
        command.display_all_tickets(long_list=True, config=cfg)
    MockSN.return_value.get_tickets.assert_called_once_with(state=TicketState.all_open)


## ── display_single_ticket ───────────────────────────────────────────────────


def test_display_single_ticket_uses_get_ticket(cfg, ticket):
    """display_single_ticket delegates lookup to get_ticket(), which searches all tickets."""
    full_ticket = ComputeAllocationRequestTicket.from_Ticket(ticket, **_FT_EXTRA_DEFAULTS)
    with patch("rcpond.command.ServiceNow") as MockSN, patch("rcpond.command.display_full_ticket"):
        MockSN.return_value.get_ticket.return_value = ticket
        MockSN.return_value.get_full_ticket.return_value = full_ticket
        command.display_single_ticket(ticket_number="RES0001000", config=cfg)
    MockSN.return_value.get_ticket.assert_called_once_with("RES0001000")


## ── _process_ticket reply_mode ──────────────────────────────────────────────


@pytest.fixture()
def mock_llm():
    llm = MagicMock(spec=LLM)
    llm.generate.return_value = LLMResponse(
        response_text="LLM reply", planned_tool_call=None, ticket_number="RES0001000", llm_model="mock-model"
    )
    return llm


## ── helpers ─────────────────────────────────────────────────────────────────

_ticket_field_names = {f.name for f in dataclasses.fields(Ticket)}
_FT_EXTRA_DEFAULTS = {
    f.name: "" for f in dataclasses.fields(ComputeAllocationRequestTicket) if f.name not in _ticket_field_names
}


## note_prefix() reads rcpond.__version__, so this must be computed at test time
def _rcpond_work_notes(timestamp: str = "01/01/2026 08:00:00") -> str:
    return f"{timestamp} - RCPond Bot (Work notes)\n{_note_prefix('post_freeform_note')}Generated response"


def _human_work_notes(timestamp: str = "01/01/2026 09:00:00") -> str:
    return f"{timestamp} - Human User (Work notes)\nHuman response"


def _make_full_ticket(ticket: Ticket, *, is_processed: bool, is_most_recent: bool) -> ComputeAllocationRequestTicket:
    """Return a real ComputeAllocationRequestTicket whose work_notes drive the actual check methods."""
    if not is_processed:
        work_notes = ""
    elif is_most_recent:
        work_notes = _rcpond_work_notes()
    else:
        ## RCPond posted earlier, human posted more recently
        work_notes = _rcpond_work_notes("01/01/2026 07:00:00") + "\n\n" + _human_work_notes()
    return ComputeAllocationRequestTicket.from_Ticket(ticket, **_FT_EXTRA_DEFAULTS, work_notes=work_notes)


def _no_change_fetch(ft: ComputeAllocationRequestTicket) -> dict[str, str]:
    """Return a _fetch_fields dict that leaves the ticket unchanged after refresh."""
    return {"work_notes": ft.work_notes, "comments": ft.comments, "state": ft.state, "assigned_to": ft.assigned_to}


## ── parametrised pre-check ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "is_processed", "is_most_recent", "expect_llm_called"),
    [
        ## cautious: skip as soon as rcpond has ever posted
        (ReplyMode.cautious, True, True, False),
        (ReplyMode.cautious, True, False, False),
        (ReplyMode.cautious, False, False, True),
        ## default: skip only when rcpond's comment or work note is the most recent
        (ReplyMode.default, True, True, False),
        (ReplyMode.default, True, False, True),  ## human posted after rcpond → proceed
        (ReplyMode.default, False, False, True),
        ## always: never skip regardless of ticket state
        (ReplyMode.always, True, True, True),
        (ReplyMode.always, True, False, True),
    ],
)
def test_reply_mode_pre_check(mode, is_processed, is_most_recent, expect_llm_called, ticket, cfg, mock_llm):
    service_now = MagicMock()
    ft = _make_full_ticket(ticket, is_processed=is_processed, is_most_recent=is_most_recent)
    service_now.get_full_ticket.return_value = ft
    ## Ensure refresh doesn't change ticket state (no post-refresh skip interference)
    service_now._fetch_fields.return_value = _no_change_fetch(ft)

    result = _process_ticket(ticket, dry_run=False, config=cfg, service_now=service_now, llm=mock_llm, reply_mode=mode)

    assert mock_llm.generate.called == expect_llm_called
    ## A skip response always has llm_model=None; an LLM response has llm_model set
    if expect_llm_called:
        assert result.llm_model == "mock-model"
    else:
        assert result.llm_model is None


## ── post-refresh race-condition ─────────────────────────────────────────────
## Another process posts while the LLM is working; the mode applies symmetrically.
## Columns: mode | initial state (passes pre-check) | work_notes after refresh | expect skip


@pytest.mark.parametrize(
    ("mode", "initial_is_processed", "initial_is_most_recent", "refresh_work_notes", "expect_skip"),
    [
        ## cautious: concurrent run posts → is_rcpond_processed becomes True → skip
        (ReplyMode.cautious, False, False, _rcpond_work_notes(), True),
        ## default: concurrent run posts → is_rcpond_most_recent_process becomes True → skip
        (ReplyMode.default, True, False, _rcpond_work_notes(), True),
        ## always: no skip even when state changes after refresh
        (ReplyMode.always, True, True, None, False),
    ],
)
def test_post_refresh_race_condition(
    mode, initial_is_processed, initial_is_most_recent, refresh_work_notes, expect_skip, ticket, cfg, mock_llm
):
    service_now = MagicMock()
    ft = _make_full_ticket(ticket, is_processed=initial_is_processed, is_most_recent=initial_is_most_recent)
    service_now.get_full_ticket.return_value = ft
    ## None → ticket state unchanged after refresh; otherwise simulate a concurrent post
    service_now._fetch_fields.return_value = (
        {"work_notes": refresh_work_notes, "comments": "", "state": "New", "assigned_to": ""}
        if refresh_work_notes is not None
        else _no_change_fetch(ft)
    )

    result = _process_ticket(ticket, dry_run=False, config=cfg, service_now=service_now, llm=mock_llm, reply_mode=mode)

    assert mock_llm.generate.called  ## pre-check always passes in these cases
    assert result.llm_model is (None if expect_skip else "mock-model")


## ── check_templates ─────────────────────────────────────────────────────────


def test_check_templates_returns_true_for_valid_templates():
    assert command.check_templates(_make_template_config(_WORKING_TEMPLATES_DIR)) is True


def test_check_templates_returns_false_when_a_template_is_malformed():
    assert command.check_templates(_make_template_config(_MOCK_TEMPLATES_DIR)) is False


def test_check_templates_returns_true_when_includes_resolve():
    assert command.check_templates(_make_template_config(_PREFIX_TEMPLATES_DIR)) is True

import base64
import dataclasses
import json
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest
import requests as _requests  ## used by test_token_introspection

from rcpond import config, servicenow
from rcpond.config import AuthMode
from rcpond.servicenow import (
    ComputeAllocationRequestTicket,
    NoteEntry,
    RelatedTicketMatch,
    ServiceNow,
    Ticket,
    TicketState,
)


def test_fullticket_alias_warns_and_resolves_to_new_class():
    with pytest.warns(DeprecationWarning, match="FullTicket is deprecated"):
        alias = servicenow.FullTicket
    assert alias is ComputeAllocationRequestTicket


def test_fullticket_alias_is_listed_in_dir():
    assert "FullTicket" in dir(servicenow)


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
        work_notes="",
        comments="",
    )


## ── Authentication wiring in __init__ ───────────────────────────────────────

_SUBSCRIPTION_KEY_HEADER = "Ocp-Apim-Subscription-Key"
_TEST_QUERY = "short_description=Request access to HPC and cloud computing facilities"


def _sn_config(auth_mode: AuthMode, servicenow_token: str | None = None) -> MagicMock:
    """A config sufficient to construct ServiceNow, in the given auth mode."""
    cfg = MagicMock()
    cfg.servicenow_auth_mode = auth_mode
    cfg.servicenow_url = "https://example.com/api/now/table"
    cfg.servicenow_web_url = "https://example.com"
    cfg.servicenow_query = _TEST_QUERY
    cfg.servicenow_token = servicenow_token
    cfg.servicenow_client_id = "cid"
    cfg.servicenow_client_secret = "csec"
    return cfg


def _make_sn(
    auth_mode: AuthMode = AuthMode.token,
    *,
    id_token: str | None = None,
    servicenow_token: str | None = "gw-key",
) -> ServiceNow:
    """Build a ServiceNow through its real constructor, then stub out the HTTP session.

    Going through ``__init__`` means the auth wiring under test — mode, headers, whether
    an id_token is adopted — is exercised rather than bypassed. Tests therefore describe
    a *configuration*, not a set of internal attributes to poke.

    The token functions are patched at their source so no browser opens and no token
    endpoint is contacted; ``id_token`` is what ``get_id_token()`` would have returned.
    """
    cfg = _sn_config(auth_mode, servicenow_token)
    with (
        patch("rcpond.auth.get_bearer_token", return_value="tok"),
        patch("rcpond.auth.get_id_token", return_value=id_token),
    ):
        sn = ServiceNow(cfg)

    ## Replace the real session; every test below asserts on calls, not on the wire.
    ## Header assertions live in test_auth_header_composition, which keeps the real one.
    sn.session = MagicMock()
    return sn


@pytest.fixture()
def sn_instance():
    """A ServiceNow in static-token mode with the HTTP session replaced by a MagicMock."""
    return _make_sn()


@pytest.mark.parametrize(
    ("auth_mode", "servicenow_token", "expect_bearer", "expect_subscription_key"),
    [
        (AuthMode.token, "gw-key", False, True),
        (AuthMode.oauth_user, None, True, False),
        (AuthMode.oauth_user, "gw-key", True, True),
        (AuthMode.oauth_client_credentials, None, True, False),
        (AuthMode.oauth_client_credentials, "gw-key", True, True),
    ],
    ids=[
        "token_sends_key_only",
        "interactive_sends_bearer_only",
        "interactive_sends_both_when_key_configured",
        "client_credentials_sends_bearer_only",
        "client_credentials_sends_both_when_key_configured",
    ],
)
def test_auth_header_composition(auth_mode, servicenow_token, expect_bearer, expect_subscription_key):
    """The gateway subscription key and the OAuth bearer are independent.

    The key authenticates the caller to the API gateway; the bearer authenticates the
    principal to ServiceNow. Either, both or neither may be needed, so presence of one
    must not suppress the other.
    """
    cfg = _sn_config(auth_mode, servicenow_token)

    with (
        patch("rcpond.auth.get_bearer_token", return_value="tok") as mock_bearer,
        patch("rcpond.auth.get_id_token", return_value=None),
    ):
        sn = ServiceNow(cfg)

    headers = sn.session.headers
    assert ("Authorization" in headers) is expect_bearer
    assert (_SUBSCRIPTION_KEY_HEADER in headers) is expect_subscription_key
    if expect_bearer:
        assert headers["Authorization"] == "Bearer tok"
    else:
        mock_bearer.assert_not_called()
    if expect_subscription_key:
        assert headers[_SUBSCRIPTION_KEY_HEADER] == servicenow_token


def test_client_credentials_does_not_adopt_a_cached_user_id_token():
    """A machine session must not inherit a human's identity from the on-disk cache.

    get_id_token() reads $XDG_CACHE_HOME/rcpond/tokens.json, which only the browser-based
    flow ever writes — a Client Credentials `rcpond login` leaves it untouched. It
    therefore holds the tokens of whoever last completed a browser login on this host,
    who need not be the person or process running now. Reading it in Client Credentials
    mode would make the bot act as that person.
    """
    cfg = _sn_config(AuthMode.oauth_client_credentials)

    with (
        patch("rcpond.auth.get_bearer_token", return_value="tok"),
        patch("rcpond.auth.get_id_token", return_value=_make_jwt("some-human-sys-id")) as mock_id_token,
    ):
        sn = ServiceNow(cfg)

    assert sn._id_token is None
    mock_id_token.assert_not_called()


## No direct test of the _acts_as_user / _is_oauth flags: they are internal derivations,
## and their observable effects are covered by test_auth_header_composition (bearer vs
## gateway key), test_client_credentials_does_not_adopt_a_cached_user_id_token (identity)
## and test_get_tickets_state_combinations (which filtering branch is taken).


def test_web_url_returns_correct_url(sn_instance, ticket):
    url = sn_instance.web_url(ticket)
    assert url == f"https://example.com/x_tati_resmgt_research.do?sys_id={ticket.sys_id}"


def test_web_url_strips_trailing_slash(sn_instance, ticket):
    sn_instance._web_base_url = "https://example.com/"
    url = sn_instance.web_url(ticket)
    assert "example.com//" not in url


## ── assign_to_me ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "auth_mode",
    [AuthMode.token, AuthMode.oauth_client_credentials],
    ids=["static_token", "client_credentials"],
)
def test_assign_to_me_raises_without_an_interactive_user(ticket, auth_mode):
    """Only the interactive flow may claim a ticket.

    Static token auth carries no identity at all. Client Credentials resolves to a
    service account and *could* technically assign — see the recorded result in
    test_client_credentials_identity_resolution — but assigning tickets to the bot is
    not believed to be a useful ServiceNow workflow, so it is blocked by choice.
    """
    sn = _make_sn(auth_mode)
    with pytest.raises(NotImplementedError, match="OAuth"):
        sn.assign_to_me(ticket)


def test_assign_to_me_calls_assign_to_with_current_user(ticket):
    """With OAuth, assign_to_me decodes the id_token sub and calls assign_to."""
    sn = _make_sn(AuthMode.oauth_user, id_token=_make_jwt("user-sys-id-123"))
    with patch.object(sn, "assign_to") as mock_assign:
        sn.assign_to_me(ticket)
    mock_assign.assert_called_once_with(ticket, "user-sys-id-123")


def test_current_user_sys_id_decodes_jwt(sn_instance):
    """_current_user_sys_id extracts the sub claim from the id_token."""
    sn_instance._id_token = _make_jwt("abc-xyz-456")
    assert sn_instance._current_user_sys_id() == "abc-xyz-456"


def test_current_user_sys_id_raises_without_id_token(sn_instance):
    """_current_user_sys_id raises RuntimeError when no id_token and sys_user fallback also fails."""
    sn_instance._id_token = None
    sn_instance.session.get.return_value.ok = False
    sn_instance.session.get.return_value.status_code = 401
    with pytest.raises(RuntimeError, match="401"):
        sn_instance._current_user_sys_id()


def test_fetch_current_user_claims_raises_on_http_error(sn_instance):
    """HTTP error from sys_user endpoint raises RuntimeError containing the status code."""
    sn_instance._id_token = None
    sn_instance.session.get.return_value.ok = False
    sn_instance.session.get.return_value.status_code = 403
    with pytest.raises(RuntimeError, match="403"):
        sn_instance._fetch_current_user_claims()


def test_fetch_current_user_claims_raises_on_empty_result(sn_instance):
    """Empty sys_user result raises RuntimeError."""
    sn_instance._id_token = None
    sn_instance.session.get.return_value.ok = True
    sn_instance.session.get.return_value.json.return_value = {"result": []}
    with pytest.raises(RuntimeError, match="no user record"):
        sn_instance._fetch_current_user_claims()


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
        "A work note...\n"
        "\n"
        "... which is extended over a blank line"
        "\n"
        "11/03/2026 11:00:21 - Research API User (Work notes)\n"
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
        NoteEntry(
            datetime(2026, 3, 11, 11, 0, 20),
            "Research API User",
            "Work notes",
            "A work note...\n\n... which is extended over a blank line",
        ),
        NoteEntry(datetime(2026, 3, 11, 11, 0, 21), "Research API User", "Work notes", "A work note"),
    ]

    actual_output = servicenow._parse_comment_display_values(input)

    assert len(actual_output) == len(expected_output)
    assert actual_output == expected_output


## ── is_rcpond_processed / is_rcpond_most_recent_process ─────────────────────


def _make_ticket(work_notes: str = "", comments: str = "") -> ComputeAllocationRequestTicket:
    """Minimal ComputeAllocationRequestTicket with controllable note strings; all other fields are empty."""
    return ComputeAllocationRequestTicket(
        sys_id="abc",
        number="RES0001000",
        opened_at="",
        requested_for="",
        u_category="",
        u_sub_category="",
        short_description="",
        state="",
        assigned_to="",
        work_notes=work_notes,
        comments=comments,
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


def _note(ts: str, user: str, content: str, note_type: str = "Work notes") -> str:
    return f"{ts} - {user} ({note_type})\n{content}"


## Simulate a note posted by an old version (pre-tool-name format, old version string).
_RCPOND_OLD = _note(
    "01/01/2026 09:00:00", "RCPond", "[code]<b>RCPond v0.0.0 generated response:</b>[/code]\n----\nOld response"
)
_RCPOND_CURRENT = _note("01/01/2026 10:00:00", "RCPond", servicenow._note_prefix("post_freeform_note") + "Response")
_HUMAN_NOTE = _note("01/01/2026 11:00:00", "Alice", "A human work note")


def test_rcpond_note_detection_no_notes():
    ticket = _make_ticket()
    assert ticket.is_rcpond_processed() is False
    assert ticket.is_rcpond_most_recent_process() is False


def test_rcpond_note_detection_only_human_notes():
    ticket = _make_ticket(work_notes=_HUMAN_NOTE)
    assert ticket.is_rcpond_processed() is False
    assert ticket.is_rcpond_most_recent_process() is False


def test_rcpond_note_detection_current_version_only():
    ticket = _make_ticket(work_notes=_RCPOND_CURRENT)
    assert ticket.is_rcpond_processed() is True
    assert ticket.is_rcpond_most_recent_process() is True


def test_rcpond_note_detection_old_version_only():
    """Old-version note: processed=True, but current version was not the last poster."""
    ticket = _make_ticket(work_notes=_RCPOND_OLD)
    assert ticket.is_rcpond_processed() is True
    assert ticket.is_rcpond_most_recent_process() is False


def test_rcpond_note_detection_current_version_in_comments():
    """Current-version note posted as a comment is detected by both methods."""
    ticket = _make_ticket(comments=_RCPOND_CURRENT)
    assert ticket.is_rcpond_processed() is True
    assert ticket.is_rcpond_most_recent_process() is True


def test_rcpond_note_detection_human_note_is_most_recent():
    """Human note posted after RCPond: processed=True, but most-recent=False."""
    notes = "\n".join([_RCPOND_CURRENT, _HUMAN_NOTE])
    ticket = _make_ticket(work_notes=notes)
    assert ticket.is_rcpond_processed() is True
    assert ticket.is_rcpond_most_recent_process() is False


def test_rcpond_note_detection_current_version_after_old():
    """Current-version note posted after old-version note: both True."""
    notes = "\n".join([_RCPOND_OLD, _RCPOND_CURRENT])
    ticket = _make_ticket(work_notes=notes)
    assert ticket.is_rcpond_processed() is True
    assert ticket.is_rcpond_most_recent_process() is True


## ── _note_prefix / _RCPOND_NOTE_RE ──────────────────────────────────────────


def test_note_prefix_includes_tool_name():
    prefix = servicenow._note_prefix("post_freeform_note")
    assert "[post_freeform_note]" in prefix
    assert prefix.startswith("[code]<b>RCPond v")


def test_note_prefix_version_override():
    prefix = servicenow._note_prefix("post_freeform_note", version="1.2.3")
    assert "v1.2.3" in prefix
    assert "[post_freeform_note]" in prefix


def test_rcpond_note_re_matches_old_format_without_tool_name():
    """Legacy notes without [tool_name] still match _RCPOND_NOTE_RE."""
    old_prefix = "[code]<b>RCPond v0.0.0 generated response:</b>[/code]\n----\n"
    assert servicenow._RCPOND_NOTE_RE.match(old_prefix)


def test_rcpond_note_re_matches_new_format_with_tool_name():
    new_prefix = servicenow._note_prefix("post_freeform_note", version="0.0.0")
    assert servicenow._RCPOND_NOTE_RE.match(new_prefix)


## ── rcpond_most_recent_tool_name ─────────────────────────────────────────────


def test_rcpond_most_recent_tool_name_returns_none_for_no_notes():
    assert _make_ticket().rcpond_most_recent_tool_name() is None


def test_rcpond_most_recent_tool_name_returns_none_for_human_note():
    assert _make_ticket(work_notes=_HUMAN_NOTE).rcpond_most_recent_tool_name() is None


def test_rcpond_most_recent_tool_name_returns_none_for_legacy_format():
    """Old-format notes (no [tool_name]) return None."""
    assert _make_ticket(work_notes=_RCPOND_OLD).rcpond_most_recent_tool_name() is None


def test_rcpond_most_recent_tool_name_returns_tool_name():
    ## _RCPOND_CURRENT uses _note_prefix("post_freeform_note")
    assert _make_ticket(work_notes=_RCPOND_CURRENT).rcpond_most_recent_tool_name() == "post_freeform_note"


def test_rcpond_most_recent_tool_name_combine_audit():
    combine_note = _note("01/01/2026 10:00:00", "RCPond", servicenow._note_prefix("combine_ticket_history") + "Audit")
    assert _make_ticket(work_notes=combine_note).rcpond_most_recent_tool_name() == "combine_ticket_history"


## ── note-classification counts (analytics) ──────────────────────────────────
## A System-authored note (e.g. the auto-close comment) is automated, not manual.
_SYSTEM_NOTE = _note(
    "01/01/2026 12:00:00",
    "System",
    "This ticket was automatically closed by the system.",
    note_type="Additional comments",
)
_EARLY_HUMAN = _note("01/01/2026 08:00:00", "Alice", "Initial human note")


@pytest.mark.parametrize(
    ("work_notes", "comments", "expected_rcpond", "expected_manual"),
    [
        ("", "", 0, 0),
        ("\n".join([_RCPOND_OLD, _RCPOND_CURRENT]), "", 2, 0),
        ("\n".join([_RCPOND_CURRENT, _HUMAN_NOTE]), "", 1, 1),
        (_RCPOND_CURRENT, _SYSTEM_NOTE, 1, 0),
    ],
    ids=["empty", "two_rcpond_versions", "rcpond_and_human", "rcpond_and_system_comment"],
)
def test_note_counts(work_notes, comments, expected_rcpond, expected_manual):
    ticket = _make_ticket(work_notes=work_notes, comments=comments)
    assert ticket.rcpond_note_count() == expected_rcpond
    assert ticket.manual_note_count() == expected_manual


@pytest.mark.parametrize(
    ("work_notes", "comments", "expected"),
    [
        (_HUMAN_NOTE, "", False),
        (_RCPOND_CURRENT, "", False),
        ("\n".join([_RCPOND_CURRENT, _HUMAN_NOTE]), "", True),
        ("\n".join([_EARLY_HUMAN, _RCPOND_CURRENT]), "", False),
        (_RCPOND_CURRENT, _SYSTEM_NOTE, False),
    ],
    ids=["no_rcpond", "rcpond_only", "human_after_rcpond", "human_before_rcpond", "system_after_rcpond"],
)
def test_has_subsequent_manual_interaction(work_notes, comments, expected):
    ticket = _make_ticket(work_notes=work_notes, comments=comments)
    assert ticket.has_subsequent_manual_interaction() is expected


## ── note/resolution timestamps (analytics, Stage 2) ─────────────────────────


@pytest.mark.parametrize(
    ("opened_at", "expected"),
    [
        ("01/01/2026 09:00:00", datetime(2026, 1, 1, 9, 0, 0)),
        ("", None),
        ("not a date", None),
    ],
    ids=["valid", "empty", "malformed"],
)
def test_opened_datetime(opened_at, expected):
    ticket = dataclasses.replace(_make_ticket(), opened_at=opened_at)
    assert ticket.opened_datetime() == expected


def test_first_note_datetimes_pick_earliest_of_each_kind():
    ticket = _make_ticket(work_notes="\n".join([_EARLY_HUMAN, _RCPOND_OLD, _RCPOND_CURRENT, _HUMAN_NOTE]))
    ## earliest RCPond note is the old-version one at 09:00; earliest manual is 08:00
    assert ticket.first_rcpond_note_datetime() == datetime(2026, 1, 1, 9, 0, 0)
    assert ticket.first_manual_note_datetime() == datetime(2026, 1, 1, 8, 0, 0)


def test_first_note_datetimes_none_when_absent():
    assert _make_ticket(work_notes=_HUMAN_NOTE).first_rcpond_note_datetime() is None
    assert _make_ticket(work_notes=_RCPOND_CURRENT).first_manual_note_datetime() is None


@pytest.mark.parametrize("state", ["Closed", "Resolved", "Cancelled"])
def test_is_closed_true_for_terminal_states(state):
    assert dataclasses.replace(_make_ticket(), state=state).is_closed() is True


@pytest.mark.parametrize("state", ["New", "In Progress", "On Hold"])
def test_is_closed_false_for_active_states(state):
    assert dataclasses.replace(_make_ticket(), state=state).is_closed() is False


def test_resolution_datetime_none_when_open():
    ticket = dataclasses.replace(_make_ticket(work_notes=_RCPOND_CURRENT), state="New")
    assert ticket.resolution_datetime() is None


def test_resolution_datetime_uses_final_note_for_closed():
    ## Final note is the System auto-close comment at 12:00.
    ticket = dataclasses.replace(_make_ticket(work_notes=_RCPOND_CURRENT, comments=_SYSTEM_NOTE), state="Closed")
    assert ticket.resolution_datetime() == datetime(2026, 1, 1, 12, 0, 0)


def test_resolution_datetime_falls_back_to_opened_at_when_no_notes():
    ticket = dataclasses.replace(_make_ticket(), state="Cancelled", opened_at="01/01/2026 09:00:00")
    assert ticket.resolution_datetime() == datetime(2026, 1, 1, 9, 0, 0)


## ── get_tickets filtering ───────────────────────────────────────────────────


def _raw_ticket(
    sys_id: str = "abc",
    number: str = "RES0001000",
    state: str = "New",
    assigned_to: str = "",
    work_notes: str = "",
    comments: str = "",
) -> dict:
    """Ticket dict in the ServiceNow API response format (plain strings for display_value fields)."""
    return {
        "sys_id": sys_id,
        "number": number,
        "opened_at": "01/01/2026 09:00:00",
        "requested_for": "Test User",
        "u_category": "HPC",
        "u_sub_category": "New",
        "short_description": "Request access to HPC and cloud computing facilities",
        "state": state,
        "assigned_to": assigned_to,
        "work_notes": work_notes,
        "comments": comments,
    }


def _setup_session(sn_instance, raw_tickets: list[dict]) -> None:
    sn_instance.session.get.return_value.json.return_value = {"result": raw_tickets}
    sn_instance.session.get.return_value.raise_for_status = MagicMock()


## OAuth/bot behaviour across TicketState values.

_COMMON_RAW_TICKETS = [
    _raw_ticket(number="unassigned_new", state="New", assigned_to=""),
    _raw_ticket(number="current_user", assigned_to="Current OAuth User"),
    _raw_ticket(number="other_user", assigned_to="A.N.Other User"),
    _raw_ticket(number="rcpond_latest_comment", work_notes=_RCPOND_CURRENT),
    _raw_ticket(number="rcpond_early_comment", work_notes=_RCPOND_OLD),
    _raw_ticket(number="human_note", work_notes=_HUMAN_NOTE),
    _raw_ticket(number="unassigned_in_progress", state="In Progress", assigned_to=""),
    _raw_ticket(number="closed", state="Closed"),
    _raw_ticket(number="resolved", state="Resolved"),
    _raw_ticket(number="cancelled", state="Cancelled"),
]


## Filtering keys on whether a human is behind the session, NOT on whether OAuth is in
## use. Client Credentials is OAuth *and* a bot, so it must produce byte-for-byte the
## same sets as static token auth — these rows are the regression guard for that.
_INTERACTIVE_ALL_OPEN = {
    "unassigned_new",
    "current_user",
    "other_user",
    "rcpond_latest_comment",
    "rcpond_early_comment",
    "human_note",
    "unassigned_in_progress",
}
_INTERACTIVE_USER_FOCUS = {
    "unassigned_new",
    "current_user",
    "rcpond_latest_comment",
    "rcpond_early_comment",
    "human_note",
    "unassigned_in_progress",
}
_BOT_ALL_OPEN = {"unassigned_new", "current_user", "other_user", "human_note", "unassigned_in_progress"}
_BOT_USER_FOCUS = {"unassigned_new", "human_note", "unassigned_in_progress"}


@pytest.mark.parametrize(
    ("auth_mode", "state", "expected"),
    [
        (AuthMode.oauth_user, TicketState.all_open, _INTERACTIVE_ALL_OPEN),
        (AuthMode.oauth_user, TicketState.user_focus, _INTERACTIVE_USER_FOCUS),
        (AuthMode.token, TicketState.all_open, _BOT_ALL_OPEN),
        (AuthMode.token, TicketState.user_focus, _BOT_USER_FOCUS),
        ## Same expectations as static token, deliberately:
        (AuthMode.oauth_client_credentials, TicketState.all_open, _BOT_ALL_OPEN),
        (AuthMode.oauth_client_credentials, TicketState.user_focus, _BOT_USER_FOCUS),
    ],
    ids=[
        "interactive_all_open",
        "interactive_user_focus",
        "static_token_all_open",
        "static_token_user_focus",
        "client_credentials_all_open_matches_bot",
        "client_credentials_user_focus_matches_bot",
    ],
)
def test_get_tickets_state_combinations(auth_mode, state, expected):
    sn = _make_sn(auth_mode)
    _setup_session(sn, _COMMON_RAW_TICKETS)

    ## The interactive path resolves a display name to filter on; the bot paths must not.
    ## Making that call explode for bots turns "routed through the wrong branch" into a
    ## failure, rather than something the expected-set comparison might mask.
    if auth_mode is AuthMode.oauth_user:
        stub = patch.object(sn, "_current_user_display_name", return_value="Current OAuth User")
    else:
        stub = patch.object(sn, "_current_user_display_name", side_effect=AssertionError("bot took the user path"))

    with stub:
        tickets = sn.get_tickets(state=state)

    assert {t.number for t in tickets} == expected


def test_get_tickets_all_including_closed_returns_everything(sn_instance):
    """TicketState.all_including_closed bypasses all filters: returns every ticket regardless of state or assignment."""

    assert sn_instance._auth_mode is AuthMode.token

    _setup_session(sn_instance, _COMMON_RAW_TICKETS)
    tickets = sn_instance.get_tickets(state=TicketState.all_including_closed)

    assert {t.number for t in tickets} == {
        "unassigned_new",
        "current_user",
        "other_user",
        "rcpond_latest_comment",
        "rcpond_early_comment",
        "human_note",
        "unassigned_in_progress",
        "closed",
        "resolved",
        "cancelled",
    }


## ── get_full_ticket dispatch ────────────────────────────────────────────────

_BASE_FIELD_NAMES = {f.name for f in dataclasses.fields(Ticket)}
_CART_EXTRA_FIELDS = {f.name for f in dataclasses.fields(ComputeAllocationRequestTicket)} - _BASE_FIELD_NAMES


def test_get_full_ticket_dispatches_to_correct_class(sn_instance, ticket):
    """A ticket matching ComputeAllocationRequestTicket.MATCH_CRITERIA is returned as that type,
    with base fields preserved and extra fields populated from the API response."""
    api_fields = {f"variables.{f}": "" for f in _CART_EXTRA_FIELDS}
    api_fields["variables.project_title"] = "My Research Project"
    sn_instance.session.get.return_value.json.return_value = {"result": api_fields}
    sn_instance.session.get.return_value.raise_for_status = MagicMock()

    result = sn_instance.get_full_ticket(ticket)

    assert isinstance(result, ComputeAllocationRequestTicket)
    assert result.number == ticket.number  # Assert the value was passed from the Base Ticket
    assert result.short_description == ticket.short_description  # Assert the value was passed from the Base Ticket
    assert result.project_title == "My Research Project"  # Assert the value was passed from the (mocked) API call


def test_get_full_ticket_raises_for_unknown_type(sn_instance, ticket):
    """A ticket matching no MATCH_CRITERIA raises ValueError naming the criteria values and known type keys."""
    unknown = dataclasses.replace(ticket, short_description="Unknown ticket type")

    with pytest.raises(ValueError) as excinfo:  # noqa: PT011 - the value is tested below
        sn_instance.get_full_ticket(unknown)

    assert "Unknown ticket type" in str(excinfo.value)  # Value is from the 'short_description' in the ticket
    assert "compute_allocation_request" in str(excinfo.value)  # Known type keys are listed in the message


## ── ticket_type_key resolver ─────────────────────────────────────────────────


def test_ticket_type_key_matches_registered_type(ticket):
    """A base ticket matching ComputeAllocationRequestTicket.MATCH_CRITERIA resolves to its registry key."""
    assert servicenow.ticket_type_key(ticket) == "compute_allocation_request"


def test_ticket_type_key_returns_none_for_unknown_type(ticket):
    """A ticket matching no registered MATCH_CRITERIA resolves to None (no exception, no message)."""
    unknown = dataclasses.replace(ticket, short_description="Unknown ticket type")
    assert servicenow.ticket_type_key(unknown) is None


## ── _current_user_sys_id / _current_user_display_name ──────────────────────


@pytest.mark.integration()
def test_client_credentials_identity_resolution(dev_instance_sn):
    """Diagnostic: what identity does a Client Credentials token resolve to on our instance?

    Answers open question §7 of planning/oauth-client-credentials.md.

    Result (dev instance, 2026-09-16)::

        Client Credentials identity claims: {
            'sub': 'b04b7606fbbd3e100b8cf46daeefdccb',
            'name': 'Research API User',
            'user_name': 'research_cmd_user',
        }

    So ``gs.getUserID()`` does resolve to the service account, as ServiceNow documents —
    and it is the same 'Research API User' that already authors RCPond's work notes.

    Identity resolution is therefore **not** the reason ``assign_to_me()`` is blocked for
    this mode. It is blocked because assigning tickets to the bot is not believed to be a
    useful ServiceNow workflow, a decision pending review with users. Do not unblock on
    the strength of this result alone.

    Re-run with a Client Credentials config against the dev instance::

        RCPOND_SERVICENOW_AUTH_MODE=oauth_client_credentials uv run pytest -m integration \\
            tests/test_servicenow.py::test_client_credentials_identity_resolution -s
    """
    if dev_instance_sn._auth_mode is not AuthMode.oauth_client_credentials:
        pytest.skip("Requires RCPOND_SERVICENOW_AUTH_MODE=oauth_client_credentials")

    ## This grant issues no id_token, so identity must come from the sys_user fallback
    assert dev_instance_sn._id_token is None, "Unexpected id_token under Client Credentials"

    try:
        claims = dev_instance_sn._fetch_current_user_claims()
    except RuntimeError as exc:
        pytest.fail(f"Client Credentials token did not resolve to any ServiceNow user: {exc}")

    print(f"\nClient Credentials identity claims: {claims}")
    print("  → Expected the service account ('Research API User'); see this test's docstring.")

    assert claims.get("sub"), "gs.getUserID() resolved no sys_id for this token"


@pytest.mark.integration()
def test_apim_userinfo_and_sys_user_me(dev_instance_sn):
    """Diagnostic: APIM userinfo (404), sys_user/me (404 — 'me' not a valid sys_id), plain sys_user (404 through APIM).
    Direct sys_user/me also 404; direct sys_user without filter returns ALL users (3 MB — not useful).
    None of these identify the current user."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")
    base = dev_instance_sn._base_api_url.removesuffix("/table")  # .../api/now

    for label, url in [
        ("APIM userinfo", f"{base}/v1/userinfo"),
        ("APIM sys_user/me", f"{dev_instance_sn._base_api_url}/sys_user/me"),
        ("APIM sys_user", f"{dev_instance_sn._base_api_url}/sys_user"),
        ("direct sys_user/me", f"{dev_instance_sn._web_base_url}/api/now/table/sys_user/me"),
        ("direct sys_user", f"{dev_instance_sn._web_base_url}/api/now/table/sys_user"),
    ]:
        resp = dev_instance_sn.session.get(url)
        print(f"\n{label}  →  HTTP {resp.status_code}")
        try:
            print(f"  body: {resp.json()}")
        except Exception:
            print(f"  body (raw): {resp.text[:200]}")


@pytest.mark.integration()
def test_apim_response_headers(dev_instance_sn):
    """Diagnostic: response headers contain X-Is-Logged-In: true but no user sys_id or name.
    APIM does not inject user-identity headers."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")
    resp = dev_instance_sn.session.get(
        f"{dev_instance_sn._base_api_url}/{dev_instance_sn._TABLE}",
        params={"sysparm_limit": "1"},
    )
    print("\nResponse headers:")
    for k, v in sorted(resp.headers.items()):
        print(f"  {k}: {v}")


@pytest.mark.integration()
def test_sys_user_lookup_via_apim(dev_instance_sn):
    """Diagnostic: sys_user/{sys_id} IS accessible through the gateway and returns full user info.
    The problem is obtaining the current user's own sys_id — not solved by this endpoint alone."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")

    ## Get a known sys_id from an assigned ticket's assignee field
    all_tickets = dev_instance_sn.get_tickets(TicketState.all_open)
    assigned = [t for t in all_tickets if t.assigned_to]
    if not assigned:
        pytest.skip("No assigned tickets available to extract a sys_id from")

    assignee = dev_instance_sn.get_assignee(assigned[0])
    sys_id = assignee["value"]
    print(f"\nUsing assignee sys_id: {sys_id!r}  (display_value: {assignee['display_value']!r})")

    resp = dev_instance_sn.session.get(
        f"{dev_instance_sn._base_api_url}/sys_user/{sys_id}",
        params={"sysparm_fields": "name,sys_id,user_name,email", "sysparm_display_value": "true"},
    )
    print(f"GET sys_user/{sys_id}  →  HTTP {resp.status_code}")
    try:
        print(f"  body: {resp.json()}")
    except Exception:
        print(f"  body (raw): {resp.text[:300]}")


@pytest.mark.integration()
def test_token_introspection(dev_instance_sn, dev_instance_config):
    """Diagnostic: POST /oauth_introspect.do returns HTTP 200 HTML login page for all auth variants.
    The endpoint is not configured as a REST API on this ServiceNow instance."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")
    token = dev_instance_sn.session.headers.get("Authorization", "").removeprefix("Bearer ")
    base_url = dev_instance_sn._web_base_url
    client_id = dev_instance_config.servicenow_client_id
    client_secret = dev_instance_config.servicenow_client_secret

    def _post(label: str, **kwargs) -> None:
        resp = _requests.post(f"{base_url}/oauth_introspect.do", **kwargs)
        print(f"\n{label}  →  HTTP {resp.status_code}")
        try:
            print(f"  body: {resp.json()}")
        except Exception:
            print(f"  body (raw): {resp.text[:300]}")

    ## Variation 1: Basic Auth + form body
    b64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    _post(
        "Basic Auth",
        headers={
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"token": token},
    )
    ## Variation 2: client credentials in form body only
    _post(
        "Form body creds",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        data={"token": token, "client_id": client_id, "client_secret": client_secret},
    )
    ## Variation 3: Bearer token, no client creds
    _post(
        "Bearer only",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"token": token},
    )


@pytest.mark.integration()
def test_current_user_sys_id(dev_instance_sn):
    """_current_user_sys_id returns a 32-char hex sys_id for the authenticated OAuth user."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")
    sys_id = dev_instance_sn._current_user_sys_id()
    assert sys_id, f"Got empty sys_id: {sys_id!r}"
    assert len(sys_id) == 32, f"Unexpected sys_id format (expected 32 hex chars): {sys_id!r}"
    assert sys_id.isalnum(), f"Unexpected sys_id format (expected 32 hex chars): {sys_id!r}"


@pytest.mark.integration()
def test_current_user_display_name(dev_instance_sn):
    """_current_user_display_name returns a non-empty display name for the authenticated OAuth user."""
    if not dev_instance_sn._is_oauth:
        pytest.skip("Requires OAuth authentication")
    name = dev_instance_sn._current_user_display_name()
    assert name is not None, "Got None — user identity could not be established (check OIDC scope and token cache)"
    assert name, f"Got empty display name: {name!r}"


@pytest.mark.integration()
def test_post_note(dev_instance_sn):
    tickets = dev_instance_sn.get_tickets()

    # get first alphanumeric ticket number
    first_num = min([t.number for t in tickets])
    my_tkt = [t for t in tickets if t.number == first_num].pop()
    print(my_tkt)
    print()

    before_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    dev_instance_sn.post_note(my_tkt, "Test Work note A", tool_name="post_freeform_note")
    dev_instance_sn.post_note(my_tkt, "Test Work note B", tool_name="post_freeform_note")

    after_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    assert after_work_note_count == before_work_note_count + 2


@pytest.mark.integration()
def test_get_tickets(dev_instance_sn):
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(TicketState.all_open)

    assert len(all_tickets) >= len(unassigned_tickets)


@pytest.mark.integration()
def test_change_assignee(dev_instance_sn):
    # Attempt to select one assigned and on unassigned ticket
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(TicketState.all_open)

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


## ── find_related_tickets ─────────────────────────────────────────────────────

_EXTRA_FIELD_DEFAULTS = {f: "" for f in _CART_EXTRA_FIELDS}


def _make_full_ticket(**overrides) -> ComputeAllocationRequestTicket:
    """Build a ComputeAllocationRequestTicket with all fields defaulting to empty string."""
    defaults: dict = {
        "sys_id": "sys_default",
        "number": "RES9990000",
        "opened_at": "01/01/2026 09:00:00",
        "requested_for": "Test User",
        "u_category": "HPC",
        "u_sub_category": "New",
        "short_description": "Request access to HPC and cloud computing facilities",
        "state": "New",
        "assigned_to": "",
        "work_notes": "",
        "comments": "",
        **_EXTRA_FIELD_DEFAULTS,
    }
    defaults.update(overrides)
    return ComputeAllocationRequestTicket(**defaults)


def _base_ticket_for(full: ComputeAllocationRequestTicket) -> Ticket:
    """Strip a full ticket down to the base Ticket fields."""
    base_fields = {f.name for f in dataclasses.fields(Ticket)}
    return Ticket(**{f: getattr(full, f) for f in base_fields})


def _setup_find_related(sn_instance, candidates: list[ComputeAllocationRequestTicket]) -> None:
    """Mock get_tickets and get_full_ticket so find_related_tickets iterates over candidates."""
    sn_instance.get_tickets = MagicMock(return_value=[_base_ticket_for(c) for c in candidates])
    sn_instance.get_full_ticket = MagicMock(side_effect=candidates)


@pytest.mark.parametrize(
    ("field", "source_value", "match_value", "no_match_value", "heuristic_substr"),
    [
        ("which_finance_code", "TUR-2023-001", "TUR-2023-001", "TUR-9999-000", "finance_code:TUR-2023-001"),
        ("pi_supervisor_email", "pi@example.com", "pi@example.com", "other@example.com", "pi_email:pi@example.com"),
        (
            "project_title",
            "Deep Learning for Climate Modelling",
            "Deep Learning for Climate Modeling",
            "Completely Different Research",
            "project_title_similarity",
        ),
        (
            "azure_subscription_id_or_hpc_group_project_id",
            "12345678-1234-1234-1234-123456789abc",
            "12345678-1234-1234-1234-123456789abc",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "12345678-1234-1234-1234-123456789abc",
        ),
    ],
    ids=["finance_code", "pi_email", "project_title", "azure_subscription_id"],
)
def test_find_related_by_heuristic(sn_instance, field, source_value, match_value, no_match_value, heuristic_substr):
    source = _make_full_ticket(number="RES0001000", **{field: source_value})
    match = _make_full_ticket(number="RES0002000", **{field: match_value})
    no_match = _make_full_ticket(number="RES0003000", **{field: no_match_value})
    _setup_find_related(sn_instance, [match, no_match])

    results = sn_instance.find_related_tickets(source)

    assert len(results) == 1
    assert results[0].ticket.number == "RES0002000"
    assert any(heuristic_substr in h for h in results[0].matched_heuristics)


def test_find_related_shared_users_reports_all_source_users(sn_instance):
    """With the default 'all shared users' heuristic, any user overlap reports every source user.

    The source lists Alice and Bob; the candidate shares only Alice. The match is still
    related, and the reported heuristics include *both* source users (not just the overlap).
    A candidate with no shared users is not related.
    """
    source = _make_full_ticket(
        number="RES0001000",
        users_who_require_access_names_and_emails="Alice Smith alice@example.com, Bob Jones bob@example.com",
    )
    match = _make_full_ticket(
        number="RES0002000",
        users_who_require_access_names_and_emails="Alice Smith alice@example.com, Bob Jones bob@example.com",
    )
    no_match = _make_full_ticket(
        number="RES0003000",
        users_who_require_access_names_and_emails="Alice Smith alice@example.com, Carol carol@example.com",
    )
    _setup_find_related(sn_instance, [match, no_match])

    results = sn_instance.find_related_tickets(source)

    assert [r.ticket.number for r in results] == ["RES0002000"]
    assert set(results[0].matched_heuristics) == {
        "shared_user:alice@example.com",
        "shared_user:bob@example.com",
    }


def test_find_related_empty_fields_do_not_match(sn_instance):
    """Empty finance code, PI email, etc. must not be treated as a match."""
    source = _make_full_ticket(
        number="RES0001000",
        which_finance_code="",
        pi_supervisor_email="",
        pmu_contact_email="",
        project_title="",
        azure_subscription_id_or_hpc_group_project_id="",
    )
    candidate = _make_full_ticket(
        number="RES0002000",
        which_finance_code="",
        pi_supervisor_email="",
        pmu_contact_email="",
        project_title="",
        azure_subscription_id_or_hpc_group_project_id="",
    )
    _setup_find_related(sn_instance, [candidate])

    results = sn_instance.find_related_tickets(source)

    assert results == []


def test_find_related_excludes_source_ticket(sn_instance):
    """The source ticket itself must never appear in the related ticket results."""
    source = _make_full_ticket(number="RES0001000", which_finance_code="TUR-2023-001")
    source_base = _base_ticket_for(source)
    sn_instance.get_tickets = MagicMock(return_value=[source_base])
    sn_instance.get_full_ticket = MagicMock()

    results = sn_instance.find_related_tickets(source)

    assert results == []
    sn_instance.get_full_ticket.assert_not_called()


def test_find_related_multiple_heuristics_in_one_match(sn_instance):
    """A ticket matching via several heuristics lists each one."""
    source = _make_full_ticket(
        number="RES0001000",
        which_finance_code="TUR-2023-001",
        pi_supervisor_email="pi@example.com",
    )
    match = _make_full_ticket(
        number="RES0002000",
        which_finance_code="TUR-2023-001",
        pi_supervisor_email="pi@example.com",
    )
    _setup_find_related(sn_instance, [match])

    results = sn_instance.find_related_tickets(source)

    assert len(results) == 1
    heuristics = results[0].matched_heuristics
    assert any("finance_code" in h for h in heuristics)
    assert any("pi_email" in h for h in heuristics)


def test_find_related_returns_relatedticketmatch_instances(sn_instance):
    source = _make_full_ticket(number="RES0001000", which_finance_code="TUR-2023-001")
    match = _make_full_ticket(number="RES0002000", which_finance_code="TUR-2023-001")
    _setup_find_related(sn_instance, [match])

    results = sn_instance.find_related_tickets(source)

    assert len(results) == 1
    assert isinstance(results[0], RelatedTicketMatch)
    assert isinstance(results[0].ticket, ComputeAllocationRequestTicket)
    assert isinstance(results[0].matched_heuristics, tuple)

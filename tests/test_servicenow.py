import base64
import dataclasses
import json
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest
import requests as _requests  ## used by test_token_introspection

from rcpond import config, servicenow
from rcpond.servicenow import ComputeAllocationRequestTicket, NoteEntry, ServiceNow, Ticket


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


@pytest.fixture()
def sn_instance():
    """A ServiceNow instance with the HTTP session replaced by a MagicMock."""
    sn = ServiceNow.__new__(ServiceNow)
    sn._base_api_url = "https://example.com/api/now/table"
    sn._web_base_url = "https://example.com"
    sn._id_token = None
    sn.session = MagicMock()
    return sn


def test_web_url_returns_correct_url(sn_instance, ticket):
    url = sn_instance.web_url(ticket)
    assert url == f"https://example.com/x_tati_resmgt_research.do?sys_id={ticket.sys_id}"


def test_web_url_strips_trailing_slash(sn_instance, ticket):
    sn_instance._web_base_url = "https://example.com/"
    url = sn_instance.web_url(ticket)
    assert "example.com//" not in url


## ── assign_to_me ────────────────────────────────────────────────────────────


def test_assign_to_me_raises_without_oauth(sn_instance, ticket):
    """Static token auth must raise NotImplementedError with a helpful message."""
    sn_instance._is_oauth = False
    with pytest.raises(NotImplementedError, match="OAuth"):
        sn_instance.assign_to_me(ticket)


def test_assign_to_me_calls_assign_to_with_current_user(sn_instance, ticket):
    """With OAuth, assign_to_me decodes the id_token sub and calls assign_to."""
    sn_instance._is_oauth = True
    sn_instance._id_token = _make_jwt("user-sys-id-123")
    with patch.object(sn_instance, "assign_to") as mock_assign:
        sn_instance.assign_to_me(ticket)
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


_RCPOND_OLD = _note("01/01/2026 09:00:00", "RCPond", servicenow._note_prefix("0.0.0") + "Old response")
_RCPOND_CURRENT = _note("01/01/2026 10:00:00", "RCPond", servicenow._note_prefix() + "Response")
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


## Closed/resolved/cancelled tickets are always excluded, regardless of auth mode or long_list.


# @pytest.mark.parametrize(("oauth", "long_list"), [(True, True), (True, False), (False, True), (False, False)])
# def test_get_tickets_excludes_closed_states(sn_instance, oauth, long_list):
#     """Should get the same result irrespective of the oauth and long_list settings"""
#     _setup_session(
#         sn_instance,
#         [
#             _raw_ticket(number="RES0000001", state="New"),
#             _raw_ticket(number="RES0000002", state="Closed"),
#             _raw_ticket(number="RES0000003", state="Resolved"),
#             _raw_ticket(number="RES0000004", state="Cancelled"),
#         ],
#     )
#     sn_instance._is_oauth = oauth
#     tickets = sn_instance.get_tickets(long_list=long_list)
#     assert [t.number for t in tickets] == ["RES0000001"]


# ## OAuth shortlist — unassigned or assigned-to-me; everything else excluded.


# def test_get_tickets_oauth_shortlist_includes_unassigned(sn_instance):
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="")])
#     sn_instance._is_oauth = True
#     with patch.object(sn_instance, "_current_user_display_name", return_value="Alice Smith"):
#         tickets = sn_instance.get_tickets()
#     assert len(tickets) == 1


# def test_get_tickets_oauth_shortlist_includes_assigned_to_me(sn_instance):
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="Alice Smith")])
#     sn_instance._is_oauth = True
#     with patch.object(sn_instance, "_current_user_display_name", return_value="Alice Smith"):
#         tickets = sn_instance.get_tickets()
#     assert len(tickets) == 1


# def test_get_tickets_oauth_shortlist_excludes_assigned_to_other(sn_instance):
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="Bob Jones")])
#     sn_instance._is_oauth = True
#     with patch.object(sn_instance, "_current_user_display_name", return_value="Alice Smith"):
#         tickets = sn_instance.get_tickets()
#     assert tickets == []


## OAuth longlist — all non-closed tickets regardless of assignment or rcpond status.


@pytest.mark.parametrize(
    ("oauth", "long_list", "expected"),
    [
        (
            True,
            True,
            {
                "unassigned_new",
                "current_user",
                "other_user",
                "rcpond_latest_comment",
                "rcpond_early_comment",
                "human_note",
                "unassigned_in_progress",
            },
        ),
        (
            True,
            False,
            {
                "unassigned_new",
                "current_user",
                "rcpond_latest_comment",
                "rcpond_early_comment",
                "human_note",
                "unassigned_in_progress",
            },
        ),
        (False, True, {"unassigned_new", "current_user", "other_user", "human_note", "unassigned_in_progress"}),
        (False, False, {"unassigned_new", "human_note", "unassigned_in_progress"}),
    ],
)
def test_get_tickets_oauth_longlist_combinations(sn_instance, oauth, long_list, expected):
    _setup_session(
        sn_instance,
        [
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
        ],
    )
    sn_instance._is_oauth = oauth

    if oauth:
        with patch.object(sn_instance, "_current_user_display_name", return_value="Current OAuth User"):
            tickets = sn_instance.get_tickets(long_list=long_list)
    else:
        tickets = sn_instance.get_tickets(long_list=long_list)

    assert {t.number for t in tickets} == expected


## Bot (static-token) shortlist — unassigned AND not rcpond_processed.


# def test_get_tickets_bot_shortlist_includes_unassigned_unprocessed(sn_instance):
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="", work_notes=_HUMAN_NOTE)])
#     sn_instance._is_oauth = False
#     tickets = sn_instance.get_tickets()
#     assert len(tickets) == 1


# def test_get_tickets_bot_shortlist_excludes_rcpond_processed(sn_instance):
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="", work_notes=_RCPOND_CURRENT)])
#     sn_instance._is_oauth = False
#     tickets = sn_instance.get_tickets()
#     assert tickets == []


# def test_get_tickets_bot_shortlist_excludes_assigned(sn_instance):
#     """Assigned tickets are excluded from the bot shortlist even if unprocessed."""
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="Bob Jones")])
#     sn_instance._is_oauth = False
#     tickets = sn_instance.get_tickets()
#     assert tickets == []


## Bot (static-token) longlist — all non-closed tickets, minus rcpond_processed.


# def test_get_tickets_bot_longlist_excludes_rcpond_processed(sn_instance):
#     _setup_session(
#         sn_instance,
#         [
#             _raw_ticket(number="RES0000001", work_notes=_RCPOND_CURRENT),
#             _raw_ticket(number="RES0000002", assigned_to="Bob Jones", work_notes=_RCPOND_CURRENT),
#         ],
#     )
#     sn_instance._is_oauth = False
#     tickets = sn_instance.get_tickets(long_list=True)
#     assert tickets == []


# def test_get_tickets_bot_longlist_includes_assigned_unprocessed(sn_instance):
#     """Bot longlist includes assigned tickets as long as RCPond has not processed them."""
#     _setup_session(sn_instance, [_raw_ticket(number="RES0000001", assigned_to="Bob Jones")])
#     sn_instance._is_oauth = False
#     tickets = sn_instance.get_tickets(long_list=True)
#     assert len(tickets) == 1


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
    assert "compute_allocation_request" in str(excinfo.value)  # Value is from the key in _TICKET_TYPES


## ── _current_user_sys_id / _current_user_display_name ──────────────────────


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
    all_tickets = dev_instance_sn.get_tickets(long_list=True)
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

    dev_instance_sn.post_note(my_tkt, "Test Work note A")
    dev_instance_sn.post_note(my_tkt, "Test Work note B")

    after_work_note_count = len(dev_instance_sn.get_work_notes(my_tkt))

    assert after_work_note_count == before_work_note_count + 2


@pytest.mark.integration()
def test_get_tickets(dev_instance_sn):
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(long_list=True)

    assert len(all_tickets) >= len(unassigned_tickets)


@pytest.mark.integration()
def test_change_assignee(dev_instance_sn):
    # Attempt to select one assigned and on unassigned ticket
    unassigned_tickets = dev_instance_sn.get_tickets()
    all_tickets = dev_instance_sn.get_tickets(long_list=True)

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

"""Tests for the rcpond CLI — auth-mode plumbing, `login` and `whoami`.

All tests are fully offline. ``rcpond.cli._config`` is patched so no config file is
read and no validation runs; the auth and ServiceNow layers are patched at their
source so no browser opens and no HTTP request is made.
"""

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from rcpond.cli import cli
from rcpond.config import AuthMode
from rcpond.servicenow import _TICKET_TYPES, DEFAULT_TICKET_TYPE

## Note: importing typer.testing raises a Click 9 DeprecationWarning from inside typer.
## The project turns warnings into errors, so pyproject's filterwarnings carries a
## narrowly-scoped ignore for it. A module-level mark cannot work — it fires at import,
## before any mark applies.


@pytest.fixture()
def mock_config():
    """A Config stand-in; the mode is what each test varies."""
    cfg = MagicMock()
    cfg.servicenow_auth_mode = AuthMode.oauth_user
    return cfg


def _invoke(args, mock_config):
    """Run the CLI with config construction stubbed out."""
    with patch("rcpond.cli._config", return_value=mock_config):
        return CliRunner().invoke(cli, args)


# --- Auth mode option plumbing ---


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["--servicenow-auth-mode", "oauth_client_credentials"], "oauth_client_credentials"),
        (["--servicenow-auth-mode", "token"], "token"),
    ],
    ids=["unset_stays_none", "explicit_client_credentials", "explicit_token"],
)
def test_auth_mode_option_forwarded_verbatim(argv, expected):
    """The callback forwards the raw flag to Config without interpreting it.

    Forwarding None when the flag is unset is what lets Config apply its own 'auto'
    resolution — a CLI-side default would pre-empt it. The value is not validated here
    either; that is Config's job, so even a mode the chosen subcommand would reject
    must pass through unchanged.

    check-templates is used as the vehicle deliberately: it is the one subcommand whose
    own docstring states that no ServiceNow configuration is required, so it has no
    auth-mode behaviour of its own to confuse matters. _config is additionally stubbed to
    abort, so no command body runs at all and every mode value reaches the assertion
    unchanged — including ones a command such as `login` would reject.
    """
    captured = {}

    def _capture_and_abort(ctx):
        captured.update(ctx.obj["cli_args"])
        raise typer.Exit(0)

    with patch("rcpond.cli._config", side_effect=_capture_and_abort):
        result = CliRunner().invoke(cli, [*argv, "check-templates"])

    assert result.exit_code == 0, result.output
    assert captured["servicenow_auth_mode"] == expected


# --- Group B: --ticket-type ---

## Group B acts on tickets of a single type. Each accepts --ticket-type and defaults to
## DEFAULT_TICKET_TYPE. See planning/multiple-ticket-types.md.
_GROUP_B_ARGV = [
    ["process-next"],
    ["process-all"],
    ["process-ticket", "RES0001234"],
    ["display-all"],
    ["display-ticket", "RES0001234"],
    ["browse-ticket", "RES0001234"],
    ["find-related", "RES0001234"],
]
## Derived, not restated, so the ids cannot drift from the argv list above.
_GROUP_B_IDS = [c[0] for c in _GROUP_B_ARGV]


def _capture_config_kwargs(argv):
    """Invoke the CLI with Config stubbed, returning the kwargs it was constructed with."""
    captured = {}

    def _capture_and_abort(**kwargs):
        captured.update(kwargs)
        raise typer.Exit(0)

    with patch("rcpond.cli.Config", side_effect=_capture_and_abort):
        result = CliRunner().invoke(cli, argv)

    return result, captured


@pytest.mark.parametrize("argv", _GROUP_B_ARGV, ids=_GROUP_B_IDS)
def test_group_b_defaults_to_the_default_ticket_type(argv):
    """Omitting --ticket-type must select the default, not fail or leave it unset.

    Leaving it unset would skip per-type config loading entirely, which is how these
    commands came to require rules and templates from the environment.
    """
    result, captured = _capture_config_kwargs(argv)

    assert result.exit_code == 0, result.output
    assert captured["cli_args"]["ticket_type"] == DEFAULT_TICKET_TYPE


@pytest.mark.parametrize("argv", _GROUP_B_ARGV, ids=_GROUP_B_IDS)
def test_group_b_accepts_an_explicit_ticket_type(argv):
    result, captured = _capture_config_kwargs([*argv, "--ticket-type", "some_other_type"])

    assert result.exit_code == 0, result.output
    assert captured["cli_args"]["ticket_type"] == "some_other_type"


def test_default_ticket_type_is_a_registered_type():
    """A default that is not in the registry would make every group B command fail."""
    assert DEFAULT_TICKET_TYPE in _TICKET_TYPES


# --- Which commands require rules and templates ---


@pytest.mark.parametrize(
    ("argv", "requires"),
    [
        (["login"], False),
        (["whoami"], False),
        (["check-templates"], True),
        (["display-all"], True),
        (["process-next", "--ticket-type", "compute_allocation_request"], True),
    ],
    ids=["login", "whoami", "check_templates", "display_all", "process_next"],
)
def test_only_auth_commands_opt_out_of_rules_and_templates(argv, requires):
    """`login` and `whoami` authenticate only, so must not demand config they never read.

    Every other command keeps the strict default. The opt-out is permanent and narrow:
    the other commands that read no rules or templates are served by `--ticket-type`
    giving them a route to a per-type config, not by exempting them here.
    """
    captured = {}

    def _capture_and_abort(**kwargs):
        captured.update(kwargs)
        raise typer.Exit(0)

    with patch("rcpond.cli.Config", side_effect=_capture_and_abort):
        result = CliRunner().invoke(cli, argv)

    assert result.exit_code == 0, result.output
    ## Commands constructing Config directly never pass the flag, so absent means strict.
    assert captured.get("require_rules_and_templates", True) is requires


# --- login ---


def test_login_interactive_reports_a_cached_token(mock_config):
    mock_config.servicenow_auth_mode = AuthMode.oauth_user

    with patch("rcpond.auth.get_bearer_token", return_value="tok") as mock_token:
        result = _invoke(["login"], mock_config)

    assert result.exit_code == 0, result.output
    mock_token.assert_called_once()
    assert "cached" in result.output.lower()


def test_login_client_credentials_does_not_claim_a_cached_token(mock_config):
    """Machine tokens live in memory for one process, so 'cached' would be a lie.

    The command still fetches a token, which makes it useful as a credentials check.
    """
    mock_config.servicenow_auth_mode = AuthMode.oauth_client_credentials

    with patch("rcpond.auth.get_bearer_token", return_value="tok") as mock_token:
        result = _invoke(["login"], mock_config)

    assert result.exit_code == 0, result.output
    mock_token.assert_called_once()
    assert "cached" not in result.output.lower()
    assert "no interactive login" in result.output.lower()


def test_login_static_token_mode_is_rejected(mock_config):
    """There is nothing to log in to without OAuth; saying so beats a confusing failure."""
    mock_config.servicenow_auth_mode = AuthMode.token

    with patch("rcpond.auth.get_bearer_token") as mock_token:
        result = _invoke(["login"], mock_config)

    assert result.exit_code != 0
    mock_token.assert_not_called()
    assert "token" in result.output.lower()


# --- whoami ---


def _patched_servicenow(auth_mode, claims=None):
    """A ServiceNow stand-in reporting the given mode and identity claims."""
    sn = MagicMock()
    sn._auth_mode = auth_mode
    sn._is_oauth = auth_mode is not AuthMode.token
    sn._acts_as_user = auth_mode is AuthMode.oauth_user
    sn._fetch_current_user_claims.return_value = claims or {}
    return sn


def test_whoami_static_token_reports_no_identity(mock_config):
    mock_config.servicenow_auth_mode = AuthMode.token
    sn = _patched_servicenow(AuthMode.token)

    with patch("rcpond.servicenow.ServiceNow", return_value=sn):
        result = _invoke(["whoami"], mock_config)

    assert result.exit_code == 0, result.output
    assert "not available" in result.output.lower()
    sn._fetch_current_user_claims.assert_not_called()


@pytest.mark.parametrize(
    ("auth_mode", "claims", "is_service_account"),
    [
        (
            AuthMode.oauth_user,
            {"name": "Ada Example", "user_name": "ada.example", "sub": "fake-user-sys-id"},
            False,
        ),
        (
            ## The name deliberately avoids the words asserted on below, so the warning
            ## check cannot be satisfied by the claims themselves.
            AuthMode.oauth_client_credentials,
            {"name": "Example Bot", "user_name": "example.bot", "sub": "fake-service-sys-id"},
            True,
        ),
    ],
    ids=["interactive", "client_credentials"],
)
def test_whoami_reports_identity_and_mode(mock_config, auth_mode, claims, is_service_account):
    """Both OAuth modes have an identity worth printing, and the mode must be stated.

    The rows carry deliberately different fake identities: under Client Credentials the
    identity is a service account rather than the person at the keyboard, so reporting a
    bare name without saying which mode produced it would be actively misleading.
    """
    mock_config.servicenow_auth_mode = auth_mode
    sn = _patched_servicenow(auth_mode, claims)

    with patch("rcpond.servicenow.ServiceNow", return_value=sn):
        result = _invoke(["whoami"], mock_config)

    assert result.exit_code == 0, result.output
    for claim_value in claims.values():
        assert claim_value in result.output
    assert auth_mode in result.output
    ## "not your own user" is the distinctive half of the warning — matching on
    ## "service account" alone would be satisfied by an identity that happens to be named
    ## one, which is exactly how an earlier version of this assertion failed to bite.
    assert ("not your own user" in result.output.lower()) is is_service_account


def test_whoami_exits_nonzero_when_identity_is_unavailable(mock_config):
    mock_config.servicenow_auth_mode = AuthMode.oauth_user
    sn = _patched_servicenow(AuthMode.oauth_user, claims={})

    with patch("rcpond.servicenow.ServiceNow", return_value=sn):
        result = _invoke(["whoami"], mock_config)

    assert result.exit_code == 1

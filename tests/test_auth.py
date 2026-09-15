"""Tests for rcpond.auth — token cache, expiry, and the get_bearer_token decision tree.

Covers both grants: the interactive Authorization Code + PKCE flow, and the
non-interactive Client Credentials flow used for machine-to-machine auth.

All tests are fully offline: no network calls, no browser launches.
The OAuth flow and loopback server helpers are patched at the module level.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from rcpond import auth
from rcpond.auth import (
    _cache_path,
    _load_cache,
    _run_client_credentials_flow,
    _save_cache,
    _token_is_expired,
    clear_token_cache,
    get_bearer_token,
    get_id_token,
)
from rcpond.config import AuthMode

# --- Fixtures ---


@pytest.fixture()
def mock_config():
    config = MagicMock()
    config.servicenow_auth_mode = AuthMode.oauth_user
    config.servicenow_client_id = "test-client-id"
    config.servicenow_client_secret = "test-client-secret"
    config.servicenow_oauth_scope = "useraccount"
    config.servicenow_oauth_redirect_port = 8765
    return config


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect XDG_CACHE_HOME to a tmp dir for every test."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_in_memory_token():
    """Clear the process-lifetime client-credentials tokens around every test.

    Module-level state, so without this a token cached by one test would leak
    into the next.
    """
    auth._CC_TOKEN_CACHE.clear()
    yield
    auth._CC_TOKEN_CACHE.clear()


# --- Cache I/O ---


def test_save_and_load_cache_round_trips():
    token = {"access_token": "abc", "refresh_token": "xyz", "expires_at": time.time() + 3600}
    _save_cache(token)
    loaded = _load_cache()
    assert loaded == token


def test_cache_file_has_restrictive_permissions():
    _save_cache({"access_token": "abc", "expires_at": time.time() + 3600})
    assert (_cache_path().stat().st_mode & 0o777) == 0o600


def test_load_cache_returns_none_when_absent():
    assert _load_cache() is None


def test_clear_token_cache_removes_file():
    _save_cache({"access_token": "abc", "expires_at": time.time() + 3600})
    assert _cache_path().exists()
    clear_token_cache()
    assert not _cache_path().exists()


def test_clear_token_cache_is_idempotent():
    ## Should not raise when no cache exists
    clear_token_cache()
    clear_token_cache()


# --- Expiry ---


def test_token_is_expired_when_expires_at_in_past():
    assert _token_is_expired({"expires_at": time.time() - 3600})


def test_token_is_not_expired_when_expires_at_in_future():
    assert not _token_is_expired({"expires_at": time.time() + 3600})


def test_token_is_expired_within_clock_skew():
    ## expires_at is 20s in the future but within the 30s clock-skew buffer
    assert _token_is_expired({"expires_at": time.time() + 20})


def test_token_is_expired_when_expires_at_missing():
    assert _token_is_expired({})


# --- get_bearer_token decision tree ---


def test_returns_cached_token_when_valid(mock_config):
    valid_token = {"access_token": "cached-token", "expires_at": time.time() + 3600}
    _save_cache(valid_token)

    with patch("rcpond.auth._run_authorization_code_flow") as mock_flow:
        result = get_bearer_token(mock_config)

    assert result == "cached-token"
    mock_flow.assert_not_called()


def test_refreshes_when_access_token_expired(mock_config):
    expired_token = {
        "access_token": "old-token",
        "refresh_token": "valid-refresh",
        "expires_at": time.time() - 60,
    }
    new_token = {"access_token": "new-token", "expires_at": time.time() + 3600}
    _save_cache(expired_token)

    with (
        patch("rcpond.auth._refresh_access_token", return_value=new_token) as mock_refresh,
        patch("rcpond.auth._run_authorization_code_flow") as mock_flow,
    ):
        result = get_bearer_token(mock_config)

    assert result == "new-token"
    mock_refresh.assert_called_once()
    mock_flow.assert_not_called()
    ## New token should be written to the cache
    assert _load_cache()["access_token"] == "new-token"


def test_falls_back_to_browser_flow_when_refresh_fails(mock_config):
    expired_token = {
        "access_token": "old-token",
        "refresh_token": "expired-refresh",
        "expires_at": time.time() - 60,
    }
    fresh_token = {"access_token": "fresh-token", "expires_at": time.time() + 3600}
    _save_cache(expired_token)

    with (
        patch("rcpond.auth._refresh_access_token", return_value=None),
        patch("rcpond.auth._run_authorization_code_flow", return_value=fresh_token) as mock_flow,
    ):
        result = get_bearer_token(mock_config)

    assert result == "fresh-token"
    mock_flow.assert_called_once()


def test_runs_browser_flow_when_no_cache(mock_config):
    fresh_token = {"access_token": "brand-new", "expires_at": time.time() + 3600}

    with patch("rcpond.auth._run_authorization_code_flow", return_value=fresh_token) as mock_flow:
        result = get_bearer_token(mock_config)

    assert result == "brand-new"
    mock_flow.assert_called_once()
    assert _load_cache()["access_token"] == "brand-new"


def test_browser_flow_not_triggered_when_no_refresh_token_but_access_valid(mock_config):
    ## No refresh token, but access token is still valid — should return cached
    token = {"access_token": "still-valid", "expires_at": time.time() + 3600}
    _save_cache(token)

    with patch("rcpond.auth._run_authorization_code_flow") as mock_flow:
        result = get_bearer_token(mock_config)

    assert result == "still-valid"
    mock_flow.assert_not_called()


# --- Client Credentials flow ---

_CC_TOKEN_URL = "https://example.service-now.com/oauth_token.do"


@pytest.fixture()
def cc_config():
    """A machine-to-machine config: client credentials, no browser-flow fields."""
    config = MagicMock()
    config.servicenow_auth_mode = AuthMode.oauth_client_credentials
    config.servicenow_client_id = "cc-client-id"
    config.servicenow_client_secret = "cc-client-secret"
    config.servicenow_oauth_scope = None
    config.servicenow_oauth_token_url = _CC_TOKEN_URL
    return config


def _cc_token(access_token: str = "cc-token", lifetime: int = 3600) -> dict:
    return {"access_token": access_token, "expires_at": time.time() + lifetime}


def _prime_cc_cache(config, token: dict) -> None:
    """Populate the in-memory cache through the public API, as a real first call would.

    Going through ``get_bearer_token`` rather than writing to the cache directly keeps
    these tests coupled to the public surface only, so a change to how the cache is
    represented cannot quietly turn them into no-ops.
    """
    with patch("rcpond.auth._run_client_credentials_flow", return_value=token):
        get_bearer_token(config)


@pytest.mark.parametrize("scope", [None, "useraccount"], ids=["no_scope", "explicit_scope"])
def test_client_credentials_flow_requests_the_client_credentials_grant(cc_config, scope):
    """The grant type must be client_credentials at both construction and token fetch."""
    cc_config.servicenow_oauth_scope = scope

    with patch("rcpond.auth.OAuth2Session") as mock_session_cls:
        mock_session_cls.return_value.fetch_token.return_value = _cc_token()
        _run_client_credentials_flow(cc_config)

    mock_session_cls.assert_called_once_with(
        client_id="cc-client-id",
        client_secret="cc-client-secret",
        scope=scope,
        grant_type="client_credentials",
    )
    mock_session_cls.return_value.fetch_token.assert_called_once_with(
        _CC_TOKEN_URL,
        grant_type="client_credentials",
    )


def test_client_credentials_never_opens_a_browser(cc_config):
    """M2M auth must be non-interactive: no browser, no loopback server, no auth-code flow."""
    with (
        patch("rcpond.auth.OAuth2Session") as mock_session_cls,
        patch("rcpond.auth.webbrowser.open") as mock_browser,
        patch("rcpond.auth._capture_redirect") as mock_redirect,
        patch("rcpond.auth._run_authorization_code_flow") as mock_auth_code,
    ):
        mock_session_cls.return_value.fetch_token.return_value = _cc_token()
        result = get_bearer_token(cc_config)

    assert result == "cc-token"
    mock_browser.assert_not_called()
    mock_redirect.assert_not_called()
    mock_auth_code.assert_not_called()


def test_client_credentials_token_is_not_written_to_the_cache_file(cc_config):
    """A machine token must never land in the shared user cache (see plan §2)."""
    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token()):
        get_bearer_token(cc_config)

    assert not _cache_path().exists()


def test_client_credentials_token_reused_within_its_lifetime(cc_config):
    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token()) as mock_flow:
        first = get_bearer_token(cc_config)
        second = get_bearer_token(cc_config)

    assert first == second == "cc-token"
    mock_flow.assert_called_once()


def test_client_credentials_token_refetched_when_expired(cc_config):
    ## A long-running bot process outlives its token; the next call must re-fetch.
    _prime_cc_cache(cc_config, {"access_token": "stale-token", "expires_at": time.time() - 60})

    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token("fresh-token")) as mock_flow:
        result = get_bearer_token(cc_config)

    assert result == "fresh-token"
    mock_flow.assert_called_once()


def test_client_credentials_does_not_attempt_a_refresh(cc_config):
    """RFC 6749 §4.4.3: the client credentials grant issues no refresh token."""
    _prime_cc_cache(
        cc_config,
        {
            "access_token": "stale-token",
            "refresh_token": "should-be-ignored",
            "expires_at": time.time() - 60,
        },
    )

    with (
        patch("rcpond.auth._refresh_access_token") as mock_refresh,
        patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token("fresh-token")),
    ):
        result = get_bearer_token(cc_config)

    assert result == "fresh-token"
    mock_refresh.assert_not_called()


def test_client_credentials_ignores_the_user_token_cache(cc_config):
    """A cached interactive-user token must not be handed to a machine session."""
    _save_cache({"access_token": "user-token", "expires_at": time.time() + 3600})

    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token()):
        result = get_bearer_token(cc_config)

    assert result == "cc-token"


def test_user_flow_ignores_the_client_credentials_token(mock_config):
    """The converse: a machine token in memory must not be handed to an interactive session.

    The only test here that writes to the cache directly: priming via the public API
    would need a second config in client-credentials mode, which would obscure what is
    being asserted. Seeded under the interactive config's own client ID, so this holds
    even when both modes share a client — the caches are separated by kind, not by key.
    """
    auth._CC_TOKEN_CACHE[mock_config.servicenow_client_id] = _cc_token("cc-token")

    with patch("rcpond.auth._run_authorization_code_flow", return_value=_cc_token("browser-token")) as mock_flow:
        result = get_bearer_token(mock_config)

    assert result == "browser-token"
    mock_flow.assert_called_once()


def test_clear_token_cache_clears_the_in_memory_token(cc_config):
    _prime_cc_cache(cc_config, _cc_token("cached-in-memory"))
    clear_token_cache()

    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token("refetched")) as mock_flow:
        result = get_bearer_token(cc_config)

    assert result == "refetched"
    mock_flow.assert_called_once()


def test_get_id_token_is_none_after_client_credentials(cc_config):
    """No end user means no id_token; identity must fall back to the sys_user lookup."""
    with patch("rcpond.auth._run_client_credentials_flow", return_value=_cc_token()):
        get_bearer_token(cc_config)

    assert get_id_token() is None


# --- Loopback server ---


def test_loopback_server_captures_code_and_state():
    """Start the loopback handler, send a mock redirect, verify captured params."""
    import threading
    import urllib.request

    from rcpond.auth import _capture_redirect

    port = 18765  ## Use a non-default port to avoid conflicts

    result: dict = {}

    def _run():
        result["params"] = _capture_redirect(port)

    thread = threading.Thread(target=_run)
    thread.start()
    ## Give the server a moment to start
    time.sleep(0.1)
    ## Use 127.0.0.1 explicitly to avoid IPv6/IPv4 resolution ambiguity on macOS
    urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=testcode&state=teststate")
    thread.join(timeout=5)

    assert result["params"]["code"] == ["testcode"]
    assert result["params"]["state"] == ["teststate"]

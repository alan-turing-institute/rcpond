"""Tests for rcpond.auth — token cache, expiry, and get_bearer_token decision tree.

All tests are fully offline: no network calls, no browser launches.
The OAuth flow and loopback server helpers are patched at the module level.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from rcpond.auth import (
    _cache_path,
    _load_cache,
    _save_cache,
    _token_is_expired,
    clear_token_cache,
    get_bearer_token,
)

# --- Fixtures ---


@pytest.fixture()
def mock_config():
    config = MagicMock()
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

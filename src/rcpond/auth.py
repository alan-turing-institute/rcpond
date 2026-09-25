"""OAuth 2.0 authentication for rcpond.

Supports two grants, selected by ``config.servicenow_auth_mode``:

- ``oauth_user``: Authorization Code + PKCE. Interactive — opens a browser and
  acts as the human user.
- ``oauth_client_credentials``: Client Credentials. Non-interactive
  machine-to-machine — acts as the service account bound to the OAuth entity.

Provides the following public functions:

- ``get_bearer_token(config)``: Return a valid Bearer token string for the
  ServiceNow API, running whichever grant the config selects.
- ``get_id_token()``: Return the ``id_token`` JWT from the cached token
  response, or ``None`` if absent (requires ``openid`` scope, so always
  ``None`` under Client Credentials).
- ``clear_token_cache()``: Delete any cached tokens, of either kind.

Authorization Code token lifecycle
----------------------------------
1. If a cached token exists and is not expired, it is returned immediately.
2. If the access token is expired but a refresh token is present, a silent
   refresh is attempted.  On success the new token is cached and returned.
3. If no usable cache is present (or refresh fails), the Authorization Code
   + PKCE flow is launched: the user's browser is opened at the ServiceNow
   authorisation URL, a local loopback server on ``localhost:<port>`` captures
   the redirect, and the code is exchanged for tokens.

Client Credentials token lifecycle
----------------------------------
The token is held in memory for the life of the process and re-fetched once it
expires.  There is no refresh step: the grant issues no refresh token
(RFC 6749 §4.4.3), and re-running it is a single non-interactive round trip.

Token caches
------------
Authorization Code tokens are stored at ``$XDG_CACHE_HOME/rcpond/tokens.json``
with mode ``0o600`` (owner-readable only).

Client Credentials tokens are deliberately **not** written there.  The file has
no notion of which principal it belongs to, so a bot and an interactive user
sharing a host would overwrite and then read each other's tokens — silently
acting as the wrong principal.  Machine tokens therefore live only in memory,
keyed by client ID.

No configuration is required beyond the ``Config`` object.
"""

import json
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from authlib.integrations.requests_client import OAuth2Session  # type: ignore[import-not-found]
from xdg_base_dirs import xdg_cache_home

from rcpond.config import AuthMode, Config

## ---- Cache helpers ----

_CACHE_DIR_NAME = "rcpond"
_CACHE_FILE_NAME = "tokens.json"
_CLOCK_SKEW_SECONDS = 30

_CC_TOKEN_CACHE: dict[str, dict] = {}
"""In-memory Client Credentials tokens, keyed by client ID.

Process-lifetime only, and never written to disk — see the module docstring.
Keying by client ID keeps two clients in one process from sharing a token."""


def _cache_path() -> Path:
    return xdg_cache_home() / _CACHE_DIR_NAME / _CACHE_FILE_NAME


def _load_cache() -> dict | None:
    """Return the cached token dict, or ``None`` if absent or unreadable."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(token_data: dict) -> None:
    """Write ``token_data`` to the cache file with restrictive permissions."""
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token_data))
    path.chmod(0o600)


def _token_is_expired(token_data: dict) -> bool:
    """Return True if the access token is expired (with clock-skew buffer)."""
    expires_at = token_data.get("expires_at")
    if expires_at is None:
        return True
    return float(expires_at) - _CLOCK_SKEW_SECONDS < time.time()


def get_id_token() -> str | None:
    """Return the id_token from the cached OAuth token response, or None if absent.

    Requires the ``openid`` scope to have been requested during authentication.
    """
    cached = _load_cache()
    return cached.get("id_token") if cached else None


def clear_token_cache() -> None:
    """Delete any cached OAuth tokens — the on-disk user cache and the in-memory machine tokens."""
    _CC_TOKEN_CACHE.clear()
    path = _cache_path()
    if path.exists():
        path.unlink()


## ---- Loopback redirect server ----


class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the OAuth redirect query string."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.server._result_queue.put(params)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authentication successful.</h2>"
            b"<p>You may close this tab and return to rcpond.</p></body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:
        ## Suppress the default request log line
        pass


def _capture_redirect(port: int) -> dict[str, list[str]]:
    """Start a loopback server on ``port``, handle one request, return query params."""
    result_queue: queue.Queue[dict] = queue.Queue()
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server._result_queue = result_queue  # type: ignore[attr-defined]

    thread = threading.Thread(target=server.handle_request)
    thread.start()
    params = result_queue.get(timeout=120)
    thread.join()
    server.server_close()
    return params


## ---- OAuth flows ----


def _run_authorization_code_flow(config: Config) -> dict:
    """Run the full browser-based Authorization Code + PKCE flow.

    Opens the user's browser at the ServiceNow authorisation URL, waits for
    the redirect on the local loopback server, exchanges the code for tokens,
    and returns the token dict.

    Parameters
    ----------
    config : Config
        Must have ``servicenow_client_id``, ``servicenow_client_secret``,
        ``servicenow_oauth_scope``, and ``servicenow_oauth_redirect_port`` set.

    Returns
    -------
    dict
        Token dict with at least ``access_token``, ``expires_at``, and
        (if issued by the server) ``refresh_token``.
    """
    assert config.servicenow_oauth_redirect_port is not None
    port = config.servicenow_oauth_redirect_port
    redirect_uri = f"http://localhost:{port}/callback"

    oauth: OAuth2Session = OAuth2Session(
        client_id=config.servicenow_client_id,
        redirect_uri=redirect_uri,
        scope=config.servicenow_oauth_scope,
    )

    authorization_url, state = oauth.create_authorization_url(
        config.servicenow_oauth_auth_url,
        code_challenge_method="S256",
    )

    print(f"\nOpening browser for ServiceNow authentication...\n  {authorization_url}\n")
    webbrowser.open(authorization_url)

    params = _capture_redirect(port)
    code = params.get("code", [None])[0]
    if code is None:
        msg = "OAuth redirect did not include a 'code' parameter"
        raise RuntimeError(msg)

    token = oauth.fetch_token(
        config.servicenow_oauth_token_url,
        code=code,
        client_secret=config.servicenow_client_secret,
        grant_type="authorization_code",
    )
    return dict(token)


def _run_client_credentials_flow(config: Config) -> dict:
    """Fetch an access token using the Client Credentials grant.

    Non-interactive: no browser, no redirect, no end user.  The token is bound to
    the service account associated with the OAuth entity in ServiceNow.

    Parameters
    ----------
    config : Config
        Must have ``servicenow_client_id``, ``servicenow_client_secret`` and
        ``servicenow_oauth_token_url`` set.  ``servicenow_oauth_scope`` is optional.

    Returns
    -------
    dict
        Token dict with at least ``access_token`` and ``expires_at``.  The grant
        issues no refresh token (RFC 6749 §4.4.3) and no ``id_token``.
    """
    ## authlib defaults to client_secret_basic. If the ServiceNow instance wants the
    ## secret in the POST body instead, pass token_endpoint_auth_method="client_secret_post".
    oauth: OAuth2Session = OAuth2Session(
        client_id=config.servicenow_client_id,
        client_secret=config.servicenow_client_secret,
        scope=config.servicenow_oauth_scope,
        grant_type="client_credentials",
    )

    token = oauth.fetch_token(
        config.servicenow_oauth_token_url,
        grant_type="client_credentials",
    )
    return dict(token)


def _refresh_access_token(config: Config, refresh_token: str) -> dict | None:
    """Attempt a silent token refresh.

    Parameters
    ----------
    config : Config
        Must have ``servicenow_client_id`` and ``servicenow_client_secret`` set.
    refresh_token : str
        The refresh token from the cache.

    Returns
    -------
    dict | None
        New token dict on success, ``None`` if the refresh failed.
    """
    try:
        oauth: OAuth2Session = OAuth2Session(
            client_id=config.servicenow_client_id,
            token={"refresh_token": refresh_token, "token_type": "Bearer"},
        )
        token = oauth.refresh_token(
            config.servicenow_oauth_token_url,
            refresh_token=refresh_token,
            client_id=config.servicenow_client_id,
            client_secret=config.servicenow_client_secret,
        )
        return dict(token)
    except Exception:
        return None


## ---- Public API ----


class BearerAuth(requests.auth.AuthBase):
    """Attach a currently-valid Bearer token to every request.

    Installed as ``session.auth`` rather than writing the ``Authorization`` header once,
    because a single client can outlive its access token: a batch run holds one
    ``ServiceNow`` for the whole job, and a header set at construction would keep being
    sent after the token lapsed, 401ing every request from then on.

    ``get_bearer_token`` is an in-memory cache hit while the token is valid, so the
    per-request cost is negligible; the point is that expiry is re-checked at all.

    Under ``oauth_client_credentials`` a lapsed token is re-fetched silently. Under
    ``oauth_user`` it is refreshed silently where possible, but a failed refresh can open
    a browser part-way through a long command — still preferable to every subsequent
    request failing.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {get_bearer_token(self._config)}"
        return request


def get_bearer_token(config: Config) -> str:
    """Return a valid Bearer token for the ServiceNow API.

    Dispatches on ``config.servicenow_auth_mode``: the Client Credentials grant for
    ``oauth_client_credentials``, otherwise the interactive Authorization Code flow.

    Parameters
    ----------
    config : Config
        For ``oauth_user``, must have ``servicenow_client_id``, ``servicenow_client_secret``,
        ``servicenow_oauth_scope`` and ``servicenow_oauth_redirect_port`` set.  For
        ``oauth_client_credentials``, must have the client credentials and
        ``servicenow_oauth_token_url`` set.

    Returns
    -------
    str
        A valid access token string.
    """
    if config.servicenow_auth_mode is AuthMode.oauth_client_credentials:
        return _get_client_credentials_token(config)
    return _get_user_token(config)


def _get_client_credentials_token(config: Config) -> str:
    """Return a valid machine token, re-fetching once the in-memory one has expired.

    Re-fetching rather than refreshing is correct here: the grant issues no refresh
    token, and a fresh fetch is a single non-interactive round trip.  Checking expiry
    on every call is what keeps a long-running bot process from 401ing part-way through.
    """
    ## Config makes client_id mandatory in this mode; assert so the cache key is typed str
    assert config.servicenow_client_id is not None
    client_id = config.servicenow_client_id
    cached = _CC_TOKEN_CACHE.get(client_id)

    if cached and not _token_is_expired(cached):
        return cached["access_token"]

    token = _run_client_credentials_flow(config)
    _CC_TOKEN_CACHE[client_id] = token
    return token["access_token"]


def _get_user_token(config: Config) -> str:
    """Return a valid interactive-user token.

    Reads from the on-disk token cache, refreshes silently if possible, and falls
    back to the full browser-based Authorization Code + PKCE flow when needed.
    """
    cached = _load_cache()

    if cached and not _token_is_expired(cached):
        return cached["access_token"]

    if cached and cached.get("refresh_token"):
        refreshed = _refresh_access_token(config, cached["refresh_token"])
        if refreshed:
            _save_cache(refreshed)
            return refreshed["access_token"]

    ## Full browser flow
    token = _run_authorization_code_flow(config)
    _save_cache(token)
    return token["access_token"]

"""OAuth 2.0 Authorization Code + PKCE authentication for rcpond.

Provides a single public function:

- ``get_bearer_token(config)``: Return a valid Bearer token string for the
  ServiceNow API, running the full browser-based flow or a silent token
  refresh as needed.
- ``clear_token_cache()``: Delete any cached tokens.

Token lifecycle
---------------
1. If a cached token exists and is not expired, it is returned immediately.
2. If the access token is expired but a refresh token is present, a silent
   refresh is attempted.  On success the new token is cached and returned.
3. If no usable cache is present (or refresh fails), the Authorization Code
   + PKCE flow is launched: the user's browser is opened at the ServiceNow
   authorisation URL, a local loopback server on ``localhost:<port>`` captures
   the redirect, and the code is exchanged for tokens.

Token cache
-----------
Tokens are stored at ``$XDG_CACHE_HOME/rcpond/tokens.json`` with mode
``0o600`` (owner-readable only).

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

from authlib.integrations.requests_client import OAuth2Session  # type: ignore[import-not-found]
from xdg_base_dirs import xdg_cache_home

from rcpond.config import Config

## ---- Cache helpers ----

_CACHE_DIR_NAME = "rcpond"
_CACHE_FILE_NAME = "tokens.json"
_CLOCK_SKEW_SECONDS = 30


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


def clear_token_cache() -> None:
    """Delete any cached OAuth tokens."""
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


def get_bearer_token(config: Config) -> str:
    """Return a valid Bearer token for the ServiceNow API.

    Reads from the token cache, refreshes silently if possible, and falls
    back to the full browser-based Authorization Code + PKCE flow when needed.

    Parameters
    ----------
    config : Config
        Must have ``servicenow_client_id``, ``servicenow_client_secret``,
        ``servicenow_oauth_scope``, and ``servicenow_oauth_redirect_port`` set.

    Returns
    -------
    str
        A valid access token string.
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

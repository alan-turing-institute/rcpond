# Supporting OAuth 2.0 Client Credentials (machine-to-machine)

## Background

RCPond currently has two authentication paths, selected implicitly in
`ServiceNow.__init__` (`src/rcpond/servicenow.py:581`):

| Condition | Path | Header sent |
|---|---|---|
| `servicenow_client_id` **and** `servicenow_client_secret` set | Authorization Code + PKCE (browser) | `Authorization: Bearer <token>` |
| otherwise | Static token | `Ocp-Apim-Subscription-Key: <servicenow_token>` |

The assumption to date has been: interactive → OAuth; non-interactive (script/bot)
→ static token from `RCPOND_SERVICENOW_TOKEN`.

This document plans a third mode: **OAuth 2.0 Client Credentials**, so a bot can
authenticate as a ServiceNow service account with a real OAuth token rather than a
static gateway key.

## Motivation

Why do this at all, given that static token auth already works for bots? The case
is mostly an IT security and compliance one.

| | Static token (`Ocp-Apim-Subscription-Key`) | Client Credentials |
|---|---|---|
| **Attribution** | Authenticates the caller to the APIM gateway, not a principal to ServiceNow. Actions are recorded against whatever integration user the route is wired to, shared with anything else holding the key. | Token is bound to a specific service account, so `sys_audit` and the ticket activity log answer "which principal changed this record". |
| **Secret on the wire** | The secret you store *is* the secret you transmit, on every request, through every hop — gateway logs, proxy logs, crash dumps, shell history. | The client secret goes to one endpoint, once per token lifetime. Everything else on the wire is a short-lived derived token. |
| **Blast radius if captured** | Valid until someone notices and manually revokes — for a key with no expiry, potentially years. | Access token dies in ~30 minutes. An open-ended incident becomes a bounded one. |
| **Revocation / rotation** | Requires finding every deployment holding the key and swapping simultaneously, so in practice it never gets rotated. | Client can be disabled centrally at the registry, tokens revoked, secret rotated with an overlap window. |
| **Authorization** | Binary — hold the key, get whatever the gateway route permits. Perimeter enforcement only. | Service account carries roles and ACLs enforced by ServiceNow itself, so least-privilege is expressible. Defence in depth. |
| **Inventory / monitoring** | Keys sprawl with no owner or register. Usage is indistinguishable from legitimate traffic. | Clients live in an enumerable registry with an owner. Token issuance is a discrete, alertable event. |

Periodic credential rotation and enumerable access for review are explicit
requirements in ISO 27001:2022 A.5.17 and the SOC 2 logical-access common
criteria; audit-trail accountability is tested directly by most frameworks.

### Why attribution matters most for RCPond

The first row is the strongest argument for *this* codebase, and it is already
visible in the code: `assign_to_me()` raises `NotImplementedError` under static
token auth (`servicenow.py:931`) precisely because there is no identity to assign
to. Every ticket mutation the bot makes today is unattributable beyond "something
holding the gateway key". That is the compliance gap this work closes — and it is
why §3.1 (whether a service-account identity actually resolves under a Client
Credentials token) is the most important of the open questions in §7.

### Honest limits of the argument

- **This does not eliminate static secrets.** The client secret is itself a
  long-lived shared secret; it has been relocated to one place with better hygiene
  around it, not removed. If it lands in the same CI variable or `.env` file the
  gateway key was in, the theft risk of the *durable* credential is roughly
  unchanged. The gains are in attribution, blast radius, revocation and inventory —
  not in "no more static secrets". The genuine step change would be
  `private_key_jwt` client assertion, mTLS, or workload identity federation, where
  no shared secret exists at all. Client Credentials with a secret is the pragmatic
  intermediate step, and worth naming as such if this needs sign-off against a
  strict secrets-management policy.
- **The gateway key may not go away.** If APIM still requires its subscription key
  alongside the bearer (§7, §4), this adds a bearer on top of the static token
  rather than replacing it. Still net positive on attribution and defence in depth,
  but do not promise otherwise until that is confirmed.
- **It is not free.** The token endpoint becomes an availability dependency, and
  token caching/expiry introduces a new class of failure. That is why §2 and §5
  bother with expiry handling rather than fetching once at startup.

## Summary of what changes

Changes **are** required — this is not a drop-in. The five substantive ones:

1. **Mode selection must become explicit.** Client Credentials uses the *same*
   two config fields (`client_id` + `client_secret`) as the current browser flow,
   so presence of those fields can no longer decide which flow to run.
2. **`_is_oauth` conflates two orthogonal things** — "how did we authenticate" and
   "is there a human user behind this session". It must be split, or M2M will
   silently inherit the interactive user's ticket-filtering behaviour.
3. **Config validation currently *requires* `openid` in the OAuth scope** — this
   would reject a Client Credentials setup outright.
4. **Token caching must not use the shared user cache file** — a machine token
   written to `~/.cache/rcpond/tokens.json` will be picked up by an interactive
   session on the same host, and vice versa.
5. **No refresh token, no `id_token`** — the identity-resolution path changes.

Everything else (request code, tools, `command.py`, `llm.py`, prompt handling) is
untouched.

---

## 1. Config: an explicit auth mode

### New field

Add to `Config` (`src/rcpond/config.py`):

```python
servicenow_auth_mode: str | None = field(init=False)
"""One of 'auto' (default), 'token', 'oauth_user', 'oauth_client_credentials'.
Selects how requests to ServiceNow are authenticated."""
```

Env var: `RCPOND_SERVICENOW_AUTH_MODE`. CLI flag: `--servicenow-auth-mode`.

### Resolution rules

`auto` (the default, and what an unset field resolves to) preserves today's
behaviour exactly:

- `client_id` + `client_secret` present → `oauth_user`
- otherwise → `token`

`oauth_client_credentials` is therefore **never** selected implicitly. This is
deliberate: inferring it from "no TTY" or "no redirect port set" is fragile, and
picking the wrong grant type fails at the ServiceNow end with an opaque error.

**Recommendation:** explicit mode field as above. The alternative — inferring M2M
from the absence of `servicenow_oauth_redirect_port` — is rejected as too implicit
for something that changes which credentials leave the machine.

### Required-field matrix

Replace the `oauth_present` / `conditionally_optional` logic at
`src/rcpond/config.py:218-247` with a per-mode table:

| Field | `token` | `oauth_user` | `oauth_client_credentials` |
|---|---|---|---|
| `servicenow_token` | required | optional | optional (see §4 on the gateway key) |
| `servicenow_client_id` | – | required | required |
| `servicenow_client_secret` | – | required | required |
| `servicenow_oauth_token_url` | – | required | **required** |
| `servicenow_oauth_auth_url` | – | required | **not used** |
| `servicenow_oauth_redirect_port` | – | required | **not used** |
| `servicenow_oauth_scope` | – | required, must contain `openid` | optional, `openid` **not** required |

Two specific edits:

- The `openid`-in-scope check (`config.py:241`) must be gated on
  `mode == "oauth_user"`. An `openid` scope on a Client Credentials grant is
  meaningless (there is no end user to identify) and ServiceNow may reject it.
- `_OAUTH_ONLY` currently makes all four OAuth-only fields required together;
  under `oauth_client_credentials` only `servicenow_oauth_token_url` is.

Also validate the mode string itself and raise a `ValueError` listing the known
modes, matching the existing `ticket_type` validation style (`config.py:268-271`).

---

## 2. `auth.py`: the Client Credentials flow

### New private function

```python
def _run_client_credentials_flow(config: Config) -> dict:
    """Fetch an access token using the Client Credentials grant (no user, no browser)."""
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
```

No new dependency — `authlib` is already a direct dependency
(`pyproject.toml:32`) and supports this grant.

One thing to confirm against the instance: whether ServiceNow expects the client
secret via HTTP Basic (`client_secret_basic`, authlib's default) or in the POST
body (`client_secret_post`). If the former fails, pass
`token_endpoint_auth_method="client_secret_post"` to `OAuth2Session`. Worth making
this a config field only if the instance turns out to need it — otherwise hardcode
whichever works.

### Caching: in-memory, not on disk

Do **not** reuse `_save_cache`/`_load_cache`. Add a module-level in-memory cache:

```python
_CC_TOKEN: dict | None = None  ## process-lifetime cache for client-credentials tokens
```

`get_bearer_token` in this mode returns `_CC_TOKEN["access_token"]` when present
and not expired (reuse the existing `_token_is_expired` helper, which already
applies the 30s clock-skew buffer), otherwise re-runs the flow.

Rationale:

- **Correctness.** `~/.cache/rcpond/tokens.json` is a single file with no notion of
  which principal it belongs to. A bot run and an interactive run on the same host
  (or two bots with different client IDs) would clobber and then read each other's
  tokens — the interactive user would silently start acting as the service account.
- **Cheapness.** A Client Credentials fetch is one non-interactive HTTP round trip.
  There is nothing to protect the user from, unlike the browser flow.
- **Expiry.** In-memory caching with an expiry check also fixes a latent issue for
  long-running bot processes: a token fetched once at startup would otherwise
  expire mid-run. Today `ServiceNow.__init__` stamps the header once and never
  refreshes it — see §5.

There is no refresh token to handle: RFC 6749 §4.4.3 says the client credentials
grant SHOULD NOT issue one, and re-running the flow is equivalent.

### Dispatch

`get_bearer_token(config)` (`auth.py:224`) becomes a dispatcher on the resolved
mode: `oauth_client_credentials` → the in-memory path above;
`oauth_user` → today's cache/refresh/browser cascade, unchanged.

`get_id_token()` returns `None` under Client Credentials (nothing writes the file
in that mode), which is already a valid return value for it — no signature change.

Add `clear_token_cache()` handling for the in-memory token too, so tests and any
future `logout` command reset both.

---

## 3. `servicenow.py`: split "OAuth" from "acts as a user"

This is the change most likely to cause a subtle regression if skipped.

`self._is_oauth` (`servicenow.py:578`) currently gates three behaviours:

- `get_tickets(user_focus)` — OAuth filters to *my* tickets by display name;
  static token filters to unassigned + not-already-processed-by-rcpond
  (`servicenow.py:619-629`)
- `get_tickets(all_open)` — static token excludes rcpond-processed tickets
- `assign_to_me()` — raises `NotImplementedError` unless OAuth (`servicenow.py:931`)
- `whoami` in the CLI (`cli.py:125`)

A Client Credentials session is OAuth *and* is a bot. If it takes the `_is_oauth`
branch it will filter tickets by the service account's display name and stop
excluding tickets rcpond has already processed — i.e. the bot's behaviour changes,
which is not what "add M2M auth" should mean.

**Plan:** replace the single flag with:

```python
self._auth_mode: str          ## 'token' | 'oauth_user' | 'oauth_client_credentials'
self._acts_as_user: bool      ## True only for 'oauth_user'
```

Then:

- **Ticket filtering** keys on `self._acts_as_user`. Client Credentials gets the
  existing bot path verbatim — no behaviour change for anyone running as a bot today.
- **`assign_to_me()`** keys on whether an identity can be resolved, not on the mode
  — see §3.1.
- Keep `_is_oauth` as a property aliasing `self._auth_mode != "token"` if anything
  outside these call sites depends on it; grep shows only `cli.py:125` does.

### 3.1 Identity under Client Credentials — a decision to make

`_fetch_current_user_claims()` (`servicenow.py:816`) tries the cached `id_token`
first, then falls back to querying `sys_user` with
`sys_id=javascript:gs.getUserID()`. That fallback is evaluated server-side and
returns whichever user the session is bound to.

ServiceNow's Client Credentials grant binds the token to a user associated with
the OAuth entity profile, so **the fallback path should return the service
account's record** — meaning `whoami` and `assign_to_me` could work under M2M
without further code. This needs verifying against the actual instance before we
rely on it; if `gs.getUserID()` resolves to `guest` or errors, identity is simply
unavailable in this mode.

Two options, pending that check:

- **(a) Recommended:** let `assign_to_me()` work when identity resolves. Change its
  guard from "is OAuth" to "try to resolve identity; raise `NotImplementedError`
  with the existing guidance if it cannot". A bot assigning tickets to its own
  service account is a genuinely useful capability.
- **(b) Conservative:** keep `assign_to_me()` restricted to `oauth_user`. Less
  code, but leaves M2M unable to claim tickets.

Either way `whoami` should print the service account's details rather than the
current "user identity not available" message, and should say which mode it is
reporting for.

---

## 4. The gateway key and the bearer token are orthogonal

`servicenow_url` points at the Azure APIM gateway
(`https://turing-api.azure-api.net/...`) while `servicenow_web_url` points at the
instance directly. Today `Ocp-Apim-Subscription-Key` is sent **only** in static
token mode, and `Authorization: Bearer` **only** in OAuth mode — they are mutually
exclusive purely as an artefact of the if/else at `servicenow.py:581-588`.

They are different things: the subscription key authenticates the *caller to the
gateway*, the bearer authenticates the *principal to ServiceNow*. Make the header
logic independent:

```python
if mode != "token":
    self.session.headers["Authorization"] = f"Bearer {get_bearer_token(config)}"
if config.servicenow_token:
    self.session.headers["Ocp-Apim-Subscription-Key"] = config.servicenow_token
```

This is backwards-compatible (in `oauth_user` mode `servicenow_token` is normally
unset, so nothing new is sent) and means an M2M deployment can present a gateway
key *and* an OAuth bearer if APIM requires both. If it turns out the gateway
rejects requests carrying both, gate the second line on `mode != "oauth_user"`.

---

## 5. Token refresh in long-running processes (optional, recommended)

`ServiceNow.__init__` sets the `Authorization` header once. For a bot process that
runs for longer than the token lifetime, every request after expiry gets a 401.
The in-memory cache from §2 only helps if something re-reads it.

Cheapest fix: mount a `requests` auth callable or a small `Session` subclass that
calls `get_bearer_token(config)` per request — the function is already a cheap
cache hit when the token is valid, and re-fetches when it is not. Worth doing as
part of this work since M2M is precisely the long-running case; it also benefits
interactive sessions that outlive a token.

Flag as optional because it is a behaviour change for the existing OAuth path.

---

## 6. CLI (`cli.py`)

- Add `--servicenow-auth-mode` to the main callback's options and to the
  `cli_args` dict (`cli.py:83-98`).
- `login` (`cli.py:105`) should short-circuit in `oauth_client_credentials` mode:
  fetching a token proves the credentials work, but the "Token cached" message is
  wrong. Print something like "Client Credentials mode — no interactive login
  required; credentials verified." after a successful fetch, so it stays usable as
  a config smoke test.
- `whoami` (`cli.py:120`) — see §3.1.
- Document in `--help` that `--servicenow-client-secret` on the command line is
  visible in the process list, and that `RCPOND_SERVICENOW_CLIENT_SECRET` is the
  right way to supply it in CI or a container.

---

## 7. ServiceNow-side prerequisites (not a code change, but blocking)

Someone with instance admin rights needs to:

- Create an OAuth application registry entry (or add to the existing one) with the
  **Client Credentials** grant type enabled.
- Associate it with a service account `sys_user` that has the roles needed to read
  and update the `x_tati_resmgt_research` table.
- Confirm the token endpoint accepts the grant, and confirm the client
  authentication method (Basic vs POST body) — see §2.
- Confirm what `gs.getUserID()` resolves to under such a token — see §3.1.
- If APIM sits in front, confirm whether a subscription key is still required
  alongside the bearer — see §4.

The last three should be checked before implementation starts; they determine
whether §3.1 option (a) and the §4 header logic are viable as written.

---

## 8. Tests

New tests in `tests/test_auth.py`, following the existing mock-`Config` pattern:

- Client Credentials fetch calls `fetch_token` with `grant_type="client_credentials"`
  and **never** opens a browser.
- No token cache **file** is written in this mode (assert `_cache_path()` absent).
- A second `get_bearer_token` call within the token lifetime does not re-fetch.
- An expired in-memory token triggers exactly one re-fetch.
- `clear_token_cache()` clears the in-memory token.

In `tests/test_config.py` (or wherever config validation is covered):

- `oauth_client_credentials` mode validates without `openid` in the scope, and
  without `auth_url` / `redirect_port`.
- `oauth_client_credentials` without `servicenow_oauth_token_url` raises.
- An unknown mode string raises with the known modes listed.
- `auto` still resolves to `oauth_user` / `token` exactly as today.

In the ServiceNow client tests:

- Header composition per mode (§4).
- `get_tickets(user_focus)` under `oauth_client_credentials` takes the **bot**
  filter path, not the per-user one — this is the regression guard for §3.

---

## 9. Docs and changelog

- `docs/configuration.md` — add "Option 3: OAuth Client Credentials (bots and CI)"
  under the existing *ServiceNow authentication* section (currently two options at
  line 150), covering the config block, the auth-mode field, and the ServiceNow
  admin prerequisites from §7. Note that `rcpond login` is not needed.
- `env.defaults` — add commented `RCPOND_SERVICENOW_AUTH_MODE` and a Client
  Credentials example block.
- `config.py` module docstring (`config.py:22-44`) — the file-format example lists
  the auth options and needs the new field.
- `auth.py` module docstring — currently titled "Authorization Code + PKCE"; it
  now covers two grants.
- `CHANGELOG.md` under `## [Unreleased]` → `Added`.

---

## Suggested order of work

1. Resolve the §7 unknowns against the ServiceNow instance (blocking for §3.1, §4).
2. `Config`: auth mode field + per-mode validation matrix (§1). Tests.
3. `auth.py`: Client Credentials flow + in-memory cache + dispatch (§2). Tests.
4. `servicenow.py`: split `_is_oauth`, header logic (§3, §4). Tests — including the
   bot-filtering regression guard.
5. `cli.py`: flag, `login`, `whoami` (§6).
6. Optional: per-request token refresh (§5).
7. Docs and changelog (§9).

Steps 2–4 are each independently shippable; after step 4 the feature works
end-to-end via env vars, with step 5 adding CLI ergonomics.

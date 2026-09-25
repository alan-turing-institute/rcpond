# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `analytics` subcommand: generates a markdown report (written to stdout) summarising RCPond performance across all tickets, per ticket type. Notes authored by the automated `System` user (e.g. auto-close comments) are treated as automated, not manual.
  - Stage 1 (processing mix): total tickets, tickets processed by RCPond, tickets processed manually (without RCPond), and RCPond tickets that had a subsequent manual interaction.
  - Stage 2 (distributions and time intervals): distribution of RCPond and manual interactions per ticket; and time intervals (in days, summarised as n/median/mean/min/max) for creation→first RCPond, creation→first manual, creation→resolution, and first RCPond→resolution. Resolution time for closed/resolved/cancelled tickets is taken from the final note (falling back to the open date); open tickets have no resolution interval.
  - Stage 3 (trends over time): a `--period {month,quarter,year}` option (default quarter) adds per-period trend tables — the processing-mix counts plus median resolution time — bucketed by each ticket's creation date.
  - Analytics is computed on a pandas DataFrame (one row per ticket) and rendered with `tabulate`; both are part of the `html` optional dependency group, which now also gates the `analytics` subcommand.
- `servicenow.ticket_type_key()`: resolves a ticket to its `_TICKET_TYPES` registry key via `MATCH_CRITERIA` (now also used by `get_full_ticket`'s dispatch).
- Note-classification and timing helpers on `Ticket`: `rcpond_note_count()`, `manual_note_count()`, `has_subsequent_manual_interaction()`, `first_rcpond_note_datetime()`, `first_manual_note_datetime()`, `is_closed()`, `resolution_datetime()`, and `opened_datetime()`.
- OAuth 2.0 **Client Credentials** authentication, for non-interactive machine-to-machine use (bots, scripts, CI). RCPond authenticates as a ServiceNow service account, giving the bot a real identity in ServiceNow, short-lived access tokens and central revocation, instead of an indefinitely valid shared subscription key.
  - New `RCPOND_SERVICENOW_AUTH_MODE` / `--servicenow-auth-mode` selects between `auto` (default), `token`, `oauth_user` and `oauth_client_credentials`. `auto` resolves to `oauth_user` when client credentials are set and `token` otherwise, so existing configurations behave exactly as before. `oauth_client_credentials` is never selected automatically: it shares its config fields with the browser flow, so it must be requested explicitly.
  - Needs only the client credentials and `RCPOND_SERVICENOW_OAUTH_TOKEN_URL`. The redirect port and authorisation URL are unused, and the scope is optional — it need not include `openid`, as there is no end user to identify.
  - Tokens are held in memory for the life of the process, keyed by client ID, and never written to the on-disk token cache. That cache has no notion of which principal it belongs to, so sharing it would let a bot and an interactive user on one host act as each other. There is no refresh step: the grant issues no refresh token, and expiry is re-checked on every call so long-running bots do not fail part-way through.
  - `rcpond login` is not required in this mode; running it verifies the credentials. `rcpond whoami` now reports the auth mode alongside the identity, and says when that identity is a service account rather than your own user.
- `--servicenow-client-secret` help now warns that a secret given on the command line is visible in the process list, and points to the environment variable instead.
- `--ticket-type` is now accepted by every command that acts on tickets of a single type: `display-ticket`, `browse-ticket`, `find-related` and `process-ticket` alongside the existing `process-next` and `process-all`. Those four previously had no way to reach a per-ticket-type config, so they could not be used with rules and templates declared only in `ticket_types/*.config`.
- RCPond now verifies that every ticket it fetches really is of the ticket type it is applying rules and templates for, and aborts naming the offending tickets if not. Because `--ticket-type` defaults rather than being required, a mismatch would otherwise be silent: a ticket of another type would be reviewed against the wrong rules and answered from the wrong email templates. A ticket matching no registered type aborts too — that means the ServiceNow query and the ticket type registry disagree, and skipping it would quietly under-process a batch. Commands that legitimately span types are unaffected.

### Changed

- The API gateway subscription key and the OAuth bearer token are now independent: `RCPOND_SERVICENOW_TOKEN` is sent whenever it is set, in any auth mode. Previously the two were mutually exclusive, so a deployment whose gateway required both could not be configured.
- Ticket filtering now keys on whether a human user is behind the session rather than on whether OAuth is in use. A Client Credentials session is OAuth-authenticated but is a bot, and sees exactly what static token auth sees; behaviour for existing token and interactive users is unchanged.
- `assign_to_me()` remains restricted to the interactive flow. The service account identity does resolve correctly under Client Credentials, so this is a product decision — assigning tickets to the bot is not believed to be a useful ServiceNow workflow — rather than a technical limitation. Under review.
- `Config.rules_path`, `Config.system_prompt_template_path` and `Config.email_templates_dir` are now typed `Path | None`. They are `None` only when the config was built with `require_rules_and_templates=False`; for every other caller they are set exactly as before. Code reading them directly must handle (or assert away) the `None` case.
- `--ticket-type` is no longer required on `process-next` and `process-all`: it defaults to `compute_allocation_request`. Passing it explicitly behaves exactly as before, but `rcpond process-next` now runs instead of erroring. The default is a fixed, named type rather than "whichever type happens to be registered", so it will not change meaning when further ticket types are added.
- `.env` files may now quote values, and a matched pair of surrounding single or double quotes is stripped. This lets one file serve both `--env-file` and `set -a; source .env; set +a`: the shell needs quotes around any value containing a space — `RCPOND_SERVICENOW_QUERY` and an `openid`-bearing `RCPOND_SERVICENOW_OAUTH_SCOPE` both do — while previously the quotes would have been read as part of the value. Unquoted and unbalanced values are unaffected.

### Fixed

- Blank `RCPOND_*` environment variables are treated as unset, so required values produce a clear missing-configuration error instead of propagating empty strings.
- A Client Credentials session no longer reads the interactive user's cached `id_token`. Only the browser-based flow ever writes the on-disk cache, so it holds the tokens of whoever last completed a browser login on that host — not necessarily the person or process running the current command. A bot sharing the host could therefore have adopted that person's identity.
- `docs/configuration.md` gave `RCPOND_SERVICENOW_OAUTH_SCOPE=workspace` in its examples, which fails validation: the interactive flow requires `openid` in the scope to obtain an `id_token`.
- `rcpond login` and `rcpond whoami` no longer require `RCPOND_RULES_PATH` and `RCPOND_EMAIL_TEMPLATES_DIR`. Both commands only authenticate and never read the rules or the email templates, but `Config` validated every field for every command — so once those values were declared solely in a per-ticket-type config, which neither command can reach (they take no `--ticket-type`), both failed with `Missing required configuration: rules_path, email_templates_dir`. `Config` gains a `require_rules_and_templates` flag, defaulting to strict, which only these two commands set. Other commands that read no rules or templates are unaffected by this change and are addressed by the per-ticket-type work.

### Notes

- The `analytics --refresh` flag is accepted but currently has no effect: a single bulk fetch is sufficient for the implemented metrics, so the ticket-history cache described in the design is deferred until a later stage needs per-ticket fetches.
- Outcome-classification metrics (a later stage) rely on the work-note tool-name prefix; tickets processed before that prefix was deployed will fall into an "unknown outcome" category.
- The ticket-type check compares each ticket's `short_description` against the registry's match criteria. `short_description` is free text that a ServiceNow administrator can reword at any time, so a reworded description will stop tickets matching and abort commands that previously worked. The fix is to update the match criteria; the alternative — carrying on with the wrong rules — is worse. Only one ticket type is registered so far, so a mismatch currently reports "matches no registered type" rather than naming the type it did match.

## [0.3.0] - 2026-06-24

### Summary of changes

This release enables RCPond to consider a project's full history when reviewing a ticket, and gives reviewers more control over when it acts:

- **Related ticket history.** When a ticket looks like part of a longer-running project, RCPond now finds the related tickets — matching on finance code, project title, the people involved, or Azure subscription — and takes their full history into account (including closed and resolved tickets) before drafting a response.
- **New `find-related` command.** Lists the tickets RCPond considers related to a given ticket and shows why each one matched, so the matching can be checked and tuned.
- **Control over re-commenting.** A new `--reply-mode` option (`cautious`, `default`, `always`) controls when RCPond skips a ticket it has already handled, so it doesn't repeat itself or talk over a colleague.

### Added

- `--reply-mode {cautious|default|always}` option for the `process-next`, `process-ticket`, and `process-all` subcommands, controlling when rcpond skips a ticket based on prior activity.
- Backward compatibility alias `rcpond.servicenow.FullTicket` for the renamed `ComputeAllocationRequestTicket` class.
- Per-ticket-type configuration: create `$XDG_CONFIG_HOME/rcpond/ticket_types/{key}.config` with `RCPOND_RULES_PATH`, `RCPOND_EMAIL_TEMPLATES_DIR`, and `RCPOND_SERVICENOW_QUERY` to configure a ticket type. The key must match an entry in the `_TICKET_TYPES` registry.
- `--ticket-type <key>` mandatory flag on `process-next` and `process-all` to specify which ticket type to process in batch commands.
- `RCPOND_SERVICENOW_QUERY` config value replaces the previously hardcoded ServiceNow query filter; falls back to the built-in default when not set.
- `find-related` subcommand: given a ticket number, lists all related tickets and which heuristic matched (finance code, PI email, PMU email, shared user email, similar project title, Azure subscription ID). Searches across all ticket states including closed and resolved.
- `TicketState` enum (`user_focus` / `all_open` / `all_including_closed`) replaces the `long_list: bool` parameter on `ServiceNow.get_tickets()`.
- `get_ticket()` now searches across all ticket states (including closed/resolved/cancelled), so that ticket numbers extracted from text fields are always resolvable.
- `combine_ticket_history` tool: a non-terminal tool the LLM can call to find related historical tickets, combine their key fields and full note history into a deterministic, audit-ready block, post it to the current ticket as an audit work note, and feed it back as context for the LLM's next turn.

### Changed

- Renamed ticket dataclass `FullTicket` to `ComputeAllocationRequestTicket` across code and docs.
- `--dry-run` now drives the full agentic loop: non-terminal tools (e.g. `combine_ticket_history`) execute read-only and feed their result back to the LLM, instead of the loop stopping at the first tool call. Each tool's `execute()` takes a `dry_run` flag and suppresses its own ServiceNow writes, so `_process_ticket` no longer special-cases dry runs.

### Deprecated

- `rcpond.servicenow.FullTicket` is deprecated and will be removed in a future release; use `ComputeAllocationRequestTicket` instead. Accessing `FullTicket` now emits a `DeprecationWarning`.

## [0.2.0] - 2026-05-27

### Added

- Ticket filtering: only unassigned tickets with a meaningful short description are returned by
  default; `--long-list` disables the filter.
- Email template files whose filenames begin with `_` (e.g. `_sign_off.j2`) are now treated as
  Jinja2 *partials*. They are excluded from the LLM's list of selectable templates but remain
  available to the Jinja renderer via `{% include %}`. Variables declared inside partials are
  still surfaced to the LLM as required parameters.

## [0.1.3] - 2026-05-18

### Added

- `browse-ticket` subcommand: opens a ticket in the default browser.
- `whoami` subcommand: shows the identity of the currently authenticated OAuth user.
- `--env-file` flag as a self-contained alternative to the default XDG config file (mutually
  exclusive with `~/.config/rcpond/default.config`).
- `comments` field on tickets (in addition to `work_notes`).
- Ticket idempotency: `process-next`, `process-ticket`, and `process-all` skip tickets that
  rcpond has already acted on (identified by a prefix on all rcpond-generated work notes).
- Race-condition guard: ticket state is re-checked after the LLM has finished to avoid acting
  on a ticket that was concurrently updated by another user.

## [0.1.2] - 2026-04-28

### Added

- `assigned_to` and `state` fields on tickets.
- Work note prefix on all rcpond-generated notes, used to identify prior rcpond activity.

## [0.1.1] - 2026-04-17

No functional changes — version bump only.

## [0.1.0] - 2026-04-17

### Added

- Core CLI built with [Typer](https://typer.tiangolo.com/), exposing the following subcommands:
  `login`, `display-all`, `display-ticket`, `process-next`, `process-ticket`, `process-all`,
  and `evaluate-all`.
- ServiceNow API client for fetching and updating HPC/cloud access request tickets.
- LLM integration via an OpenAI-compatible chat completions API (tool/function-calling support).
- OAuth 2.0 authentication (Authorization Code + PKCE flow) with browser-based login and local
  token caching under `$XDG_CACHE_HOME/rcpond/tokens.json`.
- Static subscription-key authentication as a simpler alternative to OAuth.
- Configuration loading from XDG config file (`~/.config/rcpond/default.config`), environment
  variables prefixed `RCPOND_`, and CLI flags — in increasing order of precedence.
- Rules file and system-prompt template support (`RCPOND_RULES_PATH`,
  `RCPOND_SYSTEM_PROMPT_TEMPLATE_PATH`).
- Email template system using Jinja2 (`.j2` files), with `ticket.*` fields resolved
  deterministically and all other variables generated by the LLM.
- `evaluate-all` subcommand: evaluates LLM performance against a directory of pre-downloaded
  HTML ticket files, with support for multiple runs per ticket for majority-vote analysis.
- `--dry-run` flag for `process-next`, `process-ticket`, and `process-all`: shows what rcpond
  would do without actually posting to ServiceNow.
- `--yes-i-am-sure` confirmation flag required for `process-all`.
- Read the Docs documentation site with MkDocs, including a configuration guide, API reference,
  and quick-start.

[Unreleased]: https://github.com/alan-turing-institute/rcpond/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/alan-turing-institute/rcpond/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/alan-turing-institute/rcpond/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/alan-turing-institute/rcpond/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/alan-turing-institute/rcpond/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/alan-turing-institute/rcpond/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alan-turing-institute/rcpond/releases/tag/v0.1.0

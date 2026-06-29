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

### Notes

- The `analytics --refresh` flag is accepted but currently has no effect: a single bulk fetch is sufficient for the implemented metrics, so the ticket-history cache described in the design is deferred until a later stage needs per-ticket fetches.
- Outcome-classification metrics (a later stage) rely on the work-note tool-name prefix; tickets processed before that prefix was deployed will fall into an "unknown outcome" category.

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

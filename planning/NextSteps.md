# RCPond: Current Status and Path to a Functional First Version

## What's in `main` now

### Fully implemented and tested

- **`config.py`** — Loads configuration from `.env` files, environment variables (`RCPOND_` prefix), and CLI arguments, with correct precedence. Validates that all required fields are present and that file paths exist. (26 tests)

- **`llm.py`** — LLM client that calls an OpenAI-compatible chat completions API via raw `requests`. Sends system/user messages, passes tool schemas, and parses the response into a structured `LLMResponse` (text, reasoning, planned tool call). (14 tests)

- **`prompt.py`** — Reads a rules file and a system prompt template, renders them with `str.format`, and serialises a `FullTicket` as JSON for the user prompt. (6 tests)

- **`tool.py`** — Generic wrapper that introspects a Python callable to auto-generate an OpenAI function-calling schema. (2 tests)

- **`tools.py`** — Defines the `_post_note` tool schema, provides `get_available_tools()` and a `call_tool()` dispatcher that routes LLM tool calls to their implementations. (5 tests)

### Partially implemented

- **`servicenow.py`** — `get_unassigned_tickets()` and `get_full_ticket()` work against the live API. `post_note()` and `assign_myself()` raise `RuntimeError` (not yet implemented; commented-out code sketches the approach). **No tests.**

- **`command.py`** — Four public entry points (`display_all_tickets`, `process_next_ticket`, `process_specific_ticket`, `batch_process_tickets`) wire together Config, ServiceNow, LLM, and tools. The core `_process_ticket` pipeline is complete. `_display_output()` is a stub that does nothing. **No tests.**

### Other

- **`__main__.py`** — A throwaway example that creates a Config, fetches unassigned tickets, and prints them. Not a real CLI entry point.
- **`pyproject.toml`** — Has duplicate `dev` dependency groups (`[project.optional-dependencies]` and `[dependency-groups]`) that should be merged. `pytest` is listed in core dependencies rather than dev-only.
- **`docs/`** — Placeholder files with no real content.
- **No RULES.md or system prompt template** exists in the repo, though `config.py` and `prompt.py` require paths to both.

---

## What's missing for a functional first version

Items roughly sorted by priority — earlier items block later ones.

### 1. Rules file and system prompt template

The LLM needs instructions on how to triage tickets. These two files are required by Config but don't exist anywhere in the repo yet. Without them, the pipeline cannot run.

- Create a `RULES.md` describing the triage logic (what to check, what actions to recommend).
- Create a system prompt template with a `{rules}` placeholder.

### 2. Implement `ServiceNow.post_note()`

This is the only LLM-invokable tool. Without it, the LLM can analyse tickets but cannot take any action. Commented-out code in `servicenow.py` shows the intended PATCH call — it just needs to be verified and enabled.

### 3. Implement `ServiceNow.assign_myself()`

Needed for idempotency: assign the ticket before acting on it so it won't be picked up again. The commented-out code shows a two-step approach (look up current user sys_id, then PATCH `assigned_to`). Needs verification against the actual ServiceNow instance.

### 4. Implement `_display_output()` in `command.py`

Currently a no-op. The pipeline runs but produces no visible output. Decide on format (plain text, structured table, JSON) and implement it.

### 5. Real CLI entry point

`__main__.py` is a hardcoded example. Need a proper CLI (e.g. `argparse` or `click`) that:
- Accepts a `--dry-run` flag.
- Supports subcommands or flags for list / process-next / process-specific / batch.
- Passes CLI args through to Config.
- Can be invoked as `rcpond` (register a `[project.scripts]` entry point in `pyproject.toml`).

### 6. ServiceNow tests

`servicenow.py` has zero test coverage. The plan in `planning/Plan.md` details an approach:
- Add a `TicketSource` Protocol to decouple callers from the HTTP client.
- Create a `LocalTicketSource` backed by JSON fixture files.
- Write unit tests for utility functions, mock-HTTP tests for `ServiceNow`, and protocol-conformance checks.

### 7. Command module tests

`command.py` has zero test coverage. With `TicketSource` in place, the command functions can be tested with a local source and a mocked LLM.

### 8. Refactor `ServiceNow` to accept `Config`

Currently takes a raw token string and hardcodes the base URL. As noted in `planning/pr15-review-notes.md`, it should accept a `Config` object and read `servicenow_url` and `servicenow_token` from it.

### 9. Fix `pyproject.toml` issues

- Merge the duplicate `dev` dependency groups.
- Move `pytest` from core `dependencies` to dev-only.
- Add a `[project.scripts]` entry point for the CLI.

### 10. Idempotency workflow

As raised in the PR #15 review: ensure the processing loop assigns the ticket to the current user *before* calling the LLM, so concurrent runs don't process the same ticket twice. This requires `assign_myself()` (item 3) and an update to `_process_ticket` to call it.

### 11. Additional tools beyond `post_note`

The current tool set is minimal. Depending on triage requirements, the LLM may need tools to:
- Assign tickets to specific people.
- Change ticket status or category.
- Request more information from the requestor (comment vs work note — flagged in PR #15 review).

### 12. Error handling and logging

No structured logging or error handling exists. A first version should at least:
- Log each ticket being processed.
- Handle and report API failures gracefully (ServiceNow down, LLM timeout, auth errors).
- Report dry-run vs live-run clearly.

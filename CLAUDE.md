# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

RCPond is a tool to partly automate RCP (Research Computing Platform) requests. It processes ServiceNow tickets using an LLM to review and act on them.

## Project Structure

- `src/rcpond/` — Main package source code
  - `config.py` — Configuration loading/validation from .env files, environment variables, and CLI args
  - `llm.py` — LLM client wrapping an OpenAI-compatible chat completions API
  - `servicenow.py` — ServiceNow client for managing HPC/cloud access request tickets
  - `prompt.py` — Constructs system and user prompts (system from template + rules, user from ticket JSON)
  - `tool.py` — Generic `Tool` class that wraps a callable and generates OpenAI tool schemas via introspection
  - `tools.py` — rcpond-specific tool definitions, implementations, and `call_tool` dispatcher
  - `command.py` — High-level commands: display, process next/specific, and batch-process tickets
- `tests/` — Unit tests (pytest)
- `planning/` — Design documents and specifications

## Build & Test

- **Package manager**: uv
- **Python version**: 3.13+
- **Run tests**: `uv run pytest`
- **Linting**: ruff (config in `pyproject.toml`)

## Architecture Notes

- **Config pattern**: Modules accept a config object rather than reading environment variables directly. Config is loaded via the `Config` constructor (see `config.py`).
- **LLM API**: Uses the OpenAI-compatible chat completions API via raw `requests` (not the openai SDK). The `response.json()` call returns a parsed Python dict. Tool call `function.arguments` comes as a JSON string from the API and is parsed to a dict in `_parse_response`.
- **Dataclasses**: Used throughout for data structures (`Ticket`, `FullTicket`, `LLMResponse`).
- **System prompt template**: Uses Python `str.format(rules=rules_text)` — not Jinja2. The template path comes from `config.system_prompt_template_path`. The user prompt is the full ticket serialised as JSON.
- **Tool architecture**: Generic `Tool` class in `tool.py` wraps any callable and auto-generates OpenAI function-calling schemas via introspection (name, docstring, type-annotated params). rcpond-specific tool functions and their implementations live in `tools.py`, with an `_IMPLEMENTATIONS` dict mapping tool names to lambdas that accept `(service_now, ticket, **kwargs)`.
- **Documentation style**: Each module should have lightweight inline docs following this pattern:
  - **Module docstring**: A top-level `"""..."""` summarising the module's purpose, listing its public API, describing return types, and noting configuration requirements.
  - **Class docstrings**: A brief one-liner with a usage example (`>>> ...`).
  - **Dataclass docstrings**: A one-liner on the class, plus a per-field inline docstring (`"""..."""` on the line after each field).
  - **Method docstrings**: NumPy-style with Parameters and Returns sections.
  - **Section separators**: Use `## ----` comment banners to separate logical sections (e.g. `## Interface to this module`).
  - **Inline comments**: Use `##` (double hash) comments to explain non-obvious logic.

## Notes

- Backup files (ending in `~`) exist in the repo — avoid committing these.

# Using RCPond

## Configuration

RCPond requires several credentials and paths to be configured. These can be configured in several different ways. Values are loaded from the following sources, in order of increasing precedence:

1. `$XDG_CONFIG_HOME/rcpond/default.config` (default: `~/.config/rcpond/default.config`)
2. A `.env` file passed via `--env-file`
3. Environment variables prefixed with `RCPOND_`
4. CLI flags (e.g. `--llm-api-key`)

The recommended setup is to store personal credentials once in the XDG config file
so they are available to all invocations without needing a `.env` file:

```
# ~/.config/rcpond/default.config
RCPOND_LLM_CHAT_COMPLETIONS_URL=https://...
RCPOND_LLM_API_KEY=your-api-key-here
RCPOND_LLM_MODEL=gpt-4o
RCPOND_SERVICENOW_TOKEN=your-servicenow-token
RCPOND_SERVICENOW_URL=https://turing-api.azure-api.net/dev-research/api/now/table
RCPOND_RULES_PATH=/path/to/rules.md
RCPOND_SYSTEM_PROMPT_TEMPLATE_PATH=/path/to/system_prompt_template.txt
```

A project-specific `.env` file can then override individual values where needed:

```bash
rcpond --env-file .env display-all
```

## Commands

::: mkdocs-typer
    :module: rcpond.cli
    :command: cli
    :prog_name: rcpond
    :depth: 2

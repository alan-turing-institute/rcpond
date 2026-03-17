# Using RCPond

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed (includes `uvx`)
- git+ssh access to GitHub, including the [rcpond-rules](https://github.com/alan-turing-institute/rcpond-rules) private repo


## Getting started

There are three main steps to get up and running:

- Create the configuration files.
- Obtain an ServiceNow API token and add it to the configuration.
- Installing RCPond.

## Configuration

RCPond requires several credentials and paths to be configured. These can be configured in several different ways.

### Using the default configuration file (recommended)

The recommended setup is to store personal credentials in the XDG config file. There is a helper command to create a default configuration file with most required keys:

```bash
uvx --from git+ssh://git@github.com/alan-turing-institute/rcpond-rules.git rcpond-install
```

This will install a default configuration file at `~/.config/rcpond/default.config` .

If there are existing configuration files, these will not be overwritten.

If you need to overwrite existing config files, this is possible using the `--force` option:

```bash
uvx --from git+ssh://git@github.com/alan-turing-institute/rcpond-rules.git rcpond-install --force
```

### Other configuration options

The configuration options can be provided in several different ways. This allow for testing with different credentials and using the development ServiceNow instance without needing to change the default configuration file. Values are loaded from the following sources, in order of increasing precedence:

1. `$XDG_CONFIG_HOME/rcpond/default.config` (default: `~/.config/rcpond/default.config`)
2. A `.env` file passed via `--env-file`
3. Environment variables prefixed with `RCPOND_`
4. CLI flags (e.g. `--llm-api-key`)

The recommended setup is to store personal credentials once in the XDG config file
so they are available to all invocations without needing a `.env` file:

### Configuration file example

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

## Obtaining a ServiceNow API token

For instructions on how to obtain a ServiceNow API token, see the [rcpond-rules repo](https://github.com/alan-turing-institute/rcpond-rules)

You will need to add the token to your configuration (e.g. in the XDG config file or a `.env` file) under the key `RCPOND_SERVICENOW_TOKEN` for RCPond to be able to access the ServiceNow API.

## Installing RCPond

Install RCPond using `uv`:

```bash
uv tool install git+ssh://git@github.com/alan-turing-institute/rcpond.git
rcpond
```

## RCPond Commands

<!--
Insert the module-level docstring from `rcpond.cli` here.
 ::: rcpond.cli
    options:
      show_root_heading: false
      show_source: false
      members: false
 -->

::: mkdocs-typer
    :module: rcpond.cli
    :command: cli
    :prog_name: rcpond
    :depth: 2

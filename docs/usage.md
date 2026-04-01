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
RCPOND_EMAIL_TEMPLATES_DIR=/path/to/email_templates/
```

A project-specific `.env` file can then override individual values where needed:

```bash
rcpond --env-file .env display-all
```

## Email templates

When the LLM decides to send a message to the requestor or the RCP team, it selects a Jinja2
template from `email_templates_dir` and supplies any LLM-generated variables. Templates are
`.j2` files and are rendered at runtime before being posted as a ServiceNow work note.

### Template variables

Templates typically contain multiple fields, which are rendered at runtime. These appear in the template as `{{ variable_name }}`. See the [Jinja2 documentation](https://jinja.palletsprojects.com/en/stable/templates/) for more details.

The LLM will generate values for any variables in the template that do not have the `ticket.` prefix. For example, if the template contains `{{ reason }}`, the LLM will generate a value for `reason` at call time.

Variables with the prefix `ticket.` are populated deterministically with the corresponding field from the ServiceNow ticket. For example, `{{ ticket.number }}` will be replaced with the ticket's number, and `{{ ticket.project_title }}` will be replaced with the title of the project associated with the ticket.

If a template references a field with the `ticket.` prefix that is not part of the `FullTicket` class, a validation error will be raised when the template is loaded. For example `{{ ticket.fake_field }}` will cause an error. This ensures that all `ticket.*` variables in the template correspond to actual fields on the ticket. The full list of available fields is on the [`FullTicket`](api.md#rcpond.servicenow.FullTicket) class in the API reference.


### Adding a template

Place a new `*.j2` file in `email_templates_dir`. It will be automatically picked up and
offered to the LLM as a choice the next time rcpond runs. Any variables other than `ticket.*`
fields become required LLM-supplied parameters.

Example:

```jinja
subject: Additional information required for '{{ ticket.project_title }}'
body: |
  Dear {{ ticket.requested_for }},

  We need more information about your request {{ ticket.number }}
  before we can proceed: {{ additional_info_request }}.
```

### How the LLM uses the templates

The LLM prompt includes the 'Rules' file and the full ticket information, as well as the following information about the templates:

* A list of the available templates filenames.
* The union of all of the non-`ticket.*` variables names across all templates.

The LLM does not have access to:

* The content of the templates themselves.
* Which variables belong to which templates.

Therefore it is important to use meaningful filenames for the templates. The template variables should be named in a globally consistent way across all templates.

## Commands

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

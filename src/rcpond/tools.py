"""rcpond-specific tool definitions.

Provides:

- `PostFreeformNoteTool`: Posts a freeform LLM-written note to ServiceNow.
- `PostTemplatedNoteTool`: Renders a Jinja2 template selected by the LLM and posts it.
- `CombineTicketHistoryTool`: Finds related historical tickets and combines their
  history into context (non-terminal); also posts an audit note.
- `get_available_tools`: Returns the list of tools available to the LLM.

The generic `Tool` ABC is defined in `rcpond.tool`.

Example use
-----------

```python
tools = get_available_tools(config)
response = llm.generate(system, user, model, tools=tools)
if response.planned_tool_call:
    name = response.planned_tool_call["function"]["name"]
    args = response.planned_tool_call["function"]["arguments"]
    for t in tools:
        if t.name == name:
            t.execute(service_now, ticket, **args)
```

"""

import subprocess
from pathlib import Path

import jinja2
import jinja2.meta

from rcpond.config import Config
from rcpond.servicenow import GitHubOnboardingRequestTicket, RelatedTicketMatch, ServiceNow, Ticket
from rcpond.tool import Tool

## --------------------------------------------------------------------------------
## Concrete tool implementations


class PostFreeformNoteTool(Tool):
    """Posts a freeform work note written by the LLM to the ServiceNow ticket.

    Example:
    >>> tool = PostFreeformNoteTool()
    """

    @property
    def name(self) -> str:
        return "post_freeform_note"

    @property
    def description(self) -> str:
        return "Post a freeform work note to the ServiceNow ticket, written by the LLM."

    def to_openai_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"note": {"type": "string"}},
                    "required": ["note"],
                },
            },
        }

    def execute(self, service_now: ServiceNow, ticket: Ticket, *, dry_run: bool = False, **kwargs) -> str | None:
        if not dry_run:
            service_now.post_note(ticket, note=kwargs["note"], tool_name=self.name)
        return None


class PostTemplatedNoteTool(Tool):
    """Renders a Jinja2 template selected by the LLM and posts it as a work note.

    Templates are read from ``email_templates_dir``. The ``ticket`` object is
    available in every template as ``{{ ticket.<field> }}``. All other variables
    are supplied by the LLM.

    Example:
    >>> tool = PostTemplatedNoteTool(config)
    """

    def __init__(self, config: Config) -> None:
        ## Guaranteed by Config.__post_init__ unless built with
        ## require_rules_and_templates=False, which no caller of this class should do.
        assert config.email_templates_dir is not None
        self._dir = config.email_templates_dir
        self._templates: dict[str, Path] = {f.name: f for f in sorted(self._dir.glob("*.j2"))}
        self._jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(self._dir)))

    @property
    def name(self) -> str:
        return "post_templated_note"

    @property
    def description(self) -> str:
        return (
            "Post a work note to the ServiceNow ticket using a predefined Jinja2 template. "
            "Select the most appropriate template and supply the required parameters."
        )

    def _llm_vars(self) -> set[str]:
        """Return the union of undeclared template variables across all templates, excluding 'ticket'."""
        env = jinja2.Environment()
        vars: set[str] = set()
        for path in self._templates.values():
            ast = env.parse(path.read_text())
            vars |= jinja2.meta.find_undeclared_variables(ast)
        vars.discard("ticket")
        return vars

    def _render(self, template_name: str, **kwargs) -> str:
        """Render a template by name with the given context variables.

        Parameters
        ----------
        template_name : str
            Name of the template file (relative to the templates directory).
        **kwargs
            Context variables passed to the template.

        Returns
        -------
        str
            The rendered template string.
        """
        return self._jinja_env.get_template(template_name).render(**kwargs)

    def to_openai_dict(self) -> dict:
        """Templates prefixed '_' are omitted from the template_name enum but their variables are still surfaced to the LLM."""
        llm_vars = self._llm_vars()
        properties: dict = {
            "template_name": {
                "type": "string",
                "enum": [k for k in self._templates if not k.startswith("_")],
            }
        }
        for var in sorted(llm_vars):
            properties[var] = {"type": "string"}
        required = ["template_name", *sorted(llm_vars)]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def execute(self, service_now: ServiceNow, ticket: Ticket, *, dry_run: bool = False, **kwargs) -> str | None:
        template_name = kwargs.pop("template_name")
        ## Render even in a dry run so template errors surface in the preview; only the post is suppressed.
        rendered = self._render(template_name, ticket=ticket, **kwargs)
        if not dry_run:
            service_now.post_note(ticket, note=rendered, tool_name=f"{self.name}:{template_name}")
        return None


def _format_combined_history(source: Ticket, matches: list[RelatedTicketMatch]) -> str:
    """Build a deterministic, audit-ready combined history of related tickets.

    No summarisation is performed: each related ticket's key fields and full note
    history are reproduced verbatim so the result is fully traceable for audit and
    readable by both a future LLM call and a human reviewer.

    Parameters
    ----------
    source : Ticket
        The ticket being reviewed.
    matches : list[RelatedTicketMatch]
        Related tickets as returned by ``ServiceNow.find_related_tickets()``.

    Returns
    -------
    str
        A structured block per related ticket. When ``matches`` is empty, a short
        sentence stating that no related tickets were found.
    """
    if not matches:
        return f"No related tickets were found for {source.number}."

    lines: list[str] = [
        f"Combined project history for {source.number}.",
        f"{len(matches)} related ticket(s) were found via field-matching heuristics.",
        "Each block below reproduces a related ticket's key fields and full note history verbatim.",
    ]
    for match in matches:
        t = match.ticket
        lines += [
            "",
            "=" * 80,
            f"Related ticket: {t.number}",
            f"  State: {t.state}",
            f"  Opened: {t.opened_at}",
            f"  Project title: {getattr(t, 'project_title', '') or '(none)'}",
            f"  Matched on: {', '.join(match.matched_heuristics)}",
            "",
        ]
        notes = t.get_combined_notes()
        if notes:
            lines.append("  Notes and comments:")
            for entry in notes:
                stamp = entry.datetime_stamp.strftime("%d/%m/%Y %H:%M:%S")
                lines.append(f"  [{stamp}] {entry.user} ({entry.note_type}):")
                lines += [f"    {content_line}" for content_line in entry.content.splitlines()]
        else:
            lines.append("  (no notes or comments)")
    lines.append("=" * 80)
    return "\n".join(lines)


class CombineTicketHistoryTool(Tool):
    """Finds historical tickets related to the current ticket and combines their history.

    This is a non-terminal tool: it posts the combined history to the current ticket
    as an audit note (for traceability and human readers) and returns the same
    combined history so it can be injected as context for the next LLM turn.

    Example:
    >>> tool = CombineTicketHistoryTool()
    """

    @property
    def name(self) -> str:
        return "combine_ticket_history"

    @property
    def description(self) -> str:
        return (
            "Find historical tickets related to the current ticket (by finance code, project title, "
            "shared users, PI/PMU email, or Azure subscription ID) and combine their full history into "
            "context. Call this when the ticket appears to be part of a longer-running project or "
            "references prior requests, before deciding on a response."
        )

    @property
    def is_terminal(self) -> bool:
        return False

    def to_openai_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def execute(self, service_now: ServiceNow, ticket: Ticket, *, dry_run: bool = False, **kwargs) -> str | None:
        matches = service_now.find_related_tickets(ticket)
        history = _format_combined_history(ticket, matches)
        ## Post an audit note only when there is history to preserve and this is not a dry run.
        if matches and not dry_run:
            service_now.post_note(ticket, note=history, tool_name=self.name)
        return history


class GitHubOnboardingTool(Tool):
    """
    A Tool to support the Onboarding process for the Turing's Github Organisation
    """

    @property
    def name(self) -> str:
        return "github_onboarding"

    @property
    def description(self) -> str:
        return (
            "A tool to guide the process of onboarding someone into the "
            "Turing's Github Organisation."
            "Based on the user's email address and github_username, it will"
            "determine the next step"
            "a) An admin should invite them to GitHub Org"
            "b) The user has been invited via Github and they should also be notified vis ServiceNow"
            "c) The user has been notified by ServiceNow and the ticket should be put on hold the user has accepted, or until 7 days have elapsed"
            "d) The user has accepted the invitation and the ticket should be marked as accepted and closed"
            "e) The user has not accepted the invitation and the ticket should be marked as rejected and closed"
        )

    @property
    def is_terminal(self) -> bool:
        return True

    def to_openai_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    # The email_address and github_username are not required parameters
                    # because they can be pulled directly from the ticket.
                    "properties": {},
                    "required": [],
                },
            },
        }

    def execute(self, service_now: ServiceNow, ticket: Ticket, *, dry_run: bool = False, **kwargs) -> str | None:
        assert type(ticket) is GitHubOnboardingRequestTicket

        # TODO: Find a sufficiently universal way to ensure that the 'github-users' package is
        # installed locally and available in the path
        cmd = [
            "pixi",
            "run",
            "--manifest-path /THIS/WILL/FAIL/_/PATH/TO/github-users/pyproject.toml",
            "github-users",
            "onboard",
            "--json",
            "--name",
            f"'{ticket.person_to_be_added_to_github_organisation}'",
            ticket.turing_email_address_of_the_person_being_added_to_the_github_organisation,
            ticket.github_username,
        ]

        cmd = ["echo", "hello"]

        if dry_run:
            msg = "DRY RUN!! No changes made. If run without the `--dry-run` flag the following command would have been executed:\n\n"
            cmd_str = " ".join(cmd)
            print(msg)
            print(cmd_str)
            return None

        result = subprocess.run(cmd, check=True)
        output = result.stdout
        print(f"{self.name} ran 'pixi run github-users onboard ...' and return this result:")
        print(output)
        # service_now.post_note(ticket, note=output, tool_name=self.name)
        assert service_now  # Temp line to prevent ARG002 ruff error, until the use of service_now
        # in this method is implemented
        return None


## --------------------------------------------------------------------------------
## Interface to this module


def verify_render_all_templates(config: Config) -> list[tuple[str, bool, str]]:
    """Render every top-level template with dummy variable values.

    Used for CI checks to verify all templates and their includes render
    without error via the same code path as production. Variables are filled
    as ``<name>_placeholder``; files whose names start with ``_`` are treated
    as partials and excluded from direct rendering.

    Unlike ``_llm_vars``, the variable-collection step here tolerates syntax
    errors so that each broken template is reported as a render failure rather
    than aborting the entire check.

    Returns
    -------
    list[tuple[str, bool, str]]
        One entry per top-level template: ``(name, passed, error_message)``.
        ``error_message`` is empty when ``passed`` is True.
    """
    template_tool = PostTemplatedNoteTool(config)

    ## Collect variables tolerantly: skip templates that fail to parse so that
    ## their syntax error is caught and recorded per-template at render time.
    parse_env = jinja2.Environment()
    all_vars: set[str] = set()
    for path in template_tool._templates.values():
        try:
            ast = parse_env.parse(path.read_text())
            all_vars |= jinja2.meta.find_undeclared_variables(ast)
        except jinja2.TemplateSyntaxError:
            pass
    all_vars.discard("ticket")
    dummy_context: dict = {var: f"{var}_placeholder" for var in all_vars}
    ## ticket is supplied by execute() in production; provide a stub so that
    ## {{ ticket.field }} expressions render without raising UndefinedError.
    dummy_context["ticket"] = type("_DummyTicket", (), {"__getattr__": lambda _, name: f"{name}_placeholder"})()

    results: list[tuple[str, bool, str]] = []
    for name in (n for n in template_tool._templates if not n.startswith("_")):
        try:
            template_tool._render(name, **dummy_context)
            results.append((name, True, ""))
        except jinja2.TemplateError as e:
            results.append((name, False, str(e)))
    return results


def get_available_tools(config: Config) -> list[Tool]:
    """Return the list of tools available to the LLM.

    Parameters
    ----------
    config : Config
        The loaded configuration.

    Returns
    -------
    list[Tool]
        The tools the LLM may call.
    """
    return [PostFreeformNoteTool(), PostTemplatedNoteTool(config), CombineTicketHistoryTool(), GitHubOnboardingTool()]

"""rcpond-specific tool definitions.

Provides:

- `PostFreeformNoteTool`: Posts a freeform LLM-written note to ServiceNow.
- `PostTemplatedNoteTool`: Renders a Jinja2 template selected by the LLM and posts it.
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

from pathlib import Path

import jinja2
import jinja2.meta

from rcpond.config import Config
from rcpond.servicenow import FullTicket, ServiceNow
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

    def execute(self, service_now: ServiceNow, ticket: FullTicket, **kwargs) -> None:
        service_now.post_note(ticket, note=kwargs["note"])


class PostTemplatedNoteTool(Tool):
    """Renders a Jinja2 template selected by the LLM and posts it as a work note.

    Templates are read from ``email_templates_dir``. The ``ticket`` object is
    available in every template as ``{{ ticket.<field> }}``. All other variables
    are supplied by the LLM.

    Example:
    >>> tool = PostTemplatedNoteTool(config)
    """

    def __init__(self, config: Config) -> None:
        self._dir = config.email_templates_dir
        self._templates: dict[str, Path] = {f.name: f for f in sorted(self._dir.glob("*.j2"))}

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

    def to_openai_dict(self) -> dict:
        llm_vars = self._llm_vars()
        properties: dict = {
            "template_name": {
                "type": "string",
                "enum": list(self._templates.keys()),
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

    def execute(self, service_now: ServiceNow, ticket: FullTicket, **kwargs) -> None:
        template_name = kwargs.pop("template_name")
        jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(self._dir)))
        rendered = jinja_env.get_template(template_name).render(ticket=ticket, **kwargs)
        service_now.post_note(ticket, note=rendered)


## --------------------------------------------------------------------------------
## Interface to this module


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
    return [PostFreeformNoteTool(), PostTemplatedNoteTool(config)]

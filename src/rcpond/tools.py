"""Tool definitions available to the LLM and execution of planned tool calls.

Provides:

- `Tool`: Wraps a callable, extracting its name, docstring, and parameter types for use in LLM tool schemas.
- `get_available_tools`: Returns the list of tools available to the LLM.
- `call_tool`: Executes a tool call planned by the LLM.

Example use
-----------

>>> tools = get_available_tools()
>>> tool_dicts = [t.to_openai_dict() for t in tools]
>>> response = llm.generate(system, user, model, tools=tool_dicts)
>>> if response.planned_tool_call:
...     call_tool(response.planned_tool_call, service_now, ticket)

"""

import inspect
import typing

from rcpond.servicenow import ServiceNow, Ticket

## Maps Python types to JSON Schema type strings for OpenAI tool definitions.
_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


## --------------------------------------------------------------------------------
## Tool class


class Tool:
    """Wraps a callable as an LLM tool, exposing its schema.

    Example:
    >>> def my_tool(x: str) -> None:
    ...     "Does something"
    >>> t = Tool(my_tool)

    """

    def __init__(self, func: typing.Callable):
        self.function = func
        self.name = func.__name__
        self.description = func.__doc__
        self.parameters = self._get_param_list()

    def _get_param_list(self) -> dict:
        sig = inspect.signature(self.function)
        return {name: param.annotation for name, param in sig.parameters.items()}

    def to_openai_dict(self) -> dict:
        """Convert this tool to an OpenAI function-calling schema dict.

        Returns
        -------
        dict
            A dict in the OpenAI tool format, suitable for passing to the
            chat completions API.
        """
        properties = {name: {"type": _TYPE_MAP.get(ann, "string")} for name, ann in self.parameters.items()}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(self.parameters.keys()),
                },
            },
        }


## --------------------------------------------------------------------------------
## Tool definitions (LLM-visible schema only; execution is handled by _IMPLEMENTATIONS)


def _post_note(note: str) -> None:  # noqa: ARG001
    """Post a work note to the ServiceNow ticket."""


## Maps each tool name to a callable that accepts (service_now, ticket, **tool_args).
## Add a new entry here when adding a new tool.
_IMPLEMENTATIONS: dict[str, typing.Callable] = {
    _post_note.__name__: lambda service_now, ticket, **kwargs: service_now.post_note(ticket, **kwargs),
}


## --------------------------------------------------------------------------------
## Interface to this module


def get_available_tools() -> list[Tool]:
    """Return the list of tools available to the LLM.

    Returns
    -------
    list[Tool]
        The tools the LLM may call.
    """
    return [Tool(_post_note)]


def call_tool(planned_tool_call: dict, service_now: ServiceNow, ticket: Ticket) -> None:
    """Execute a tool call planned by the LLM.

    Parameters
    ----------
    planned_tool_call : dict
        The tool call from the LLM response to execute. Expected shape:
        ``{"function": {"name": str, "arguments": dict}}``.
    service_now : ServiceNow
        The ServiceNow client used to perform the action.
    ticket : Ticket
        The ticket the action should be applied to.

    Raises
    ------
    ValueError
        If the tool name is not recognised.
    """
    name = planned_tool_call["function"]["name"]
    args = planned_tool_call["function"]["arguments"]

    if name not in _IMPLEMENTATIONS:
        msg = f"Unknown tool: {name!r}"
        raise ValueError(msg)

    _IMPLEMENTATIONS[name](service_now, ticket, **args)

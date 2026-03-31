"""Generic LLM tool wrapper.

Provides:

- `Tool`: Wraps a callable, extracting its name, docstring, and LLM-visible
  parameter types for use in LLM tool schemas.

The callable passed to `Tool` is the tool's implementation. Parameters typed as
`ServiceNow` or `Ticket` are treated as runtime context and excluded from the
OpenAI schema; all other parameters are exposed to the LLM.

Example use
-----------

>>> from rcpond.servicenow import ServiceNow, Ticket
>>> def my_tool(service_now: ServiceNow, ticket: Ticket, note: str) -> None:
...     "Post a note."
...     service_now.post_note(ticket, note=note)
>>> t = Tool(my_tool)
>>> t.to_openai_dict()
{'type': 'function', 'function': {'name': 'my_tool', ...}}

"""

import inspect
import typing

from rcpond.servicenow import ServiceNow, Ticket

## Maps Python types to JSON Schema type strings for OpenAI tool definitions.
_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}

## Parameters of these types are runtime context, not LLM-provided arguments.
_CONTEXT_TYPES = {ServiceNow, Ticket}


## --------------------------------------------------------------------------------
## Tool class


class Tool:
    """Wraps a callable as an LLM tool, exposing its schema and implementation.

    Example:
    >>> def my_tool(service_now: ServiceNow, ticket: Ticket, x: str) -> None:
    ...     "Does something"
    >>> t = Tool(my_tool)

    """

    def __init__(self, func: typing.Callable) -> None:
        self.name = func.__name__
        self.description = func.__doc__
        self.impl = func
        self.parameters = self._get_param_list()

    def _get_param_list(self) -> dict:
        sig = inspect.signature(self.impl)
        return {
            name: param.annotation for name, param in sig.parameters.items() if param.annotation not in _CONTEXT_TYPES
        }

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

    def execute(self, service_now: ServiceNow, ticket: Ticket, **kwargs) -> None:
        """Execute this tool's implementation.

        Parameters
        ----------
        service_now : ServiceNow
            The ServiceNow client used to perform the action.
        ticket : Ticket
            The ticket the action should be applied to.
        **kwargs
            Arguments from the LLM's tool call.
        """
        self.impl(service_now, ticket, **kwargs)

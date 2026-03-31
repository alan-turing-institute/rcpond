"""rcpond-specific tool definitions.

Provides:

- `get_available_tools`: Returns the list of tools available to the LLM.

The generic `Tool` class used here is defined in `rcpond.tool`.

Example use
-----------

>>> tools = get_available_tools()
>>> response = llm.generate(system, user, model, tools=tools)
>>> if response.planned_tool_call:
...     name = response.planned_tool_call["function"]["name"]
...     args = response.planned_tool_call["function"]["arguments"]
...     for t in tools:
...         if t.name == name:
...             t.execute(service_now, ticket, **args)

"""

from rcpond.servicenow import ServiceNow, Ticket
from rcpond.tool import Tool

## --------------------------------------------------------------------------------
## Tool implementations


def post_freeform_note(service_now: ServiceNow, ticket: Ticket, note: str) -> None:
    """Post a work note to the ServiceNow ticket. The note is freeform and written by the LLM"""
    service_now.post_note(ticket, note=note)


## --------------------------------------------------------------------------------
## Interface to this module


def get_available_tools() -> list[Tool]:
    """Return the list of tools available to the LLM.

    Returns
    -------
    list[Tool]
        The tools the LLM may call.
    """
    return [Tool(post_freeform_note)]

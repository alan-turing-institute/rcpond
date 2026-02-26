"""Tool definitions available to the LLM and execution of planned tool calls."""

import typing
from dataclasses import dataclass
import inspect

class Tool:
    def __init__(self, func: typing.Callable):
        self.function = func
        self.name = func.__name__
        self.description = func.__doc__
        self.parameters = self._get_param_list()

    def _get_param_list(self) -> dict:
        sig = inspect.signature(self.function)
        return {name: param.annotation for name, param in sig.parameters.items()}


def get_available_tools(**kwargs) -> list[Tool]:
    """
    Returns a list of the tools available to the LLM.
    In then short term this is only expected to be one
    tool "servicenow_comment_on_ticket".


    Parameters
    ----------
    kwargs: this is a placeholder. In practise the tools might be dependant on other
    component or configuration values. For example the tool "servicenow_comment_on_ticket"
    will probably need access the ServiceNow object.
    """


def call_tool(planned_tool_call: dict) -> None:  # noqa: ARG001
    """Execute a tool call planned by the LLM.

    Parameters
    ----------
    planned_tool_call : dict
        The tool call from the LLM response to execute.
    """
    # Determine which tool is being called
    # Execute the appropriate tool with the provided arguments

"""Generic LLM tool wrapper.

Provides:

- `Tool`: Wraps a callable, extracting its name, docstring, and parameter types for use in LLM tool schemas.

Example use
-----------

>>> def my_tool(x: str) -> None:
...     "Does something"
>>> t = Tool(my_tool)
>>> t.to_openai_dict()
{'type': 'function', 'function': {'name': 'my_tool', ...}}

"""

import inspect
import typing

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

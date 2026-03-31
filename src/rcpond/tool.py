"""Generic LLM tool interface.

Provides:

- `Tool`: Abstract base class for LLM tools. Each tool exposes its schema via
  ``to_openai_dict()`` and runs its action via ``execute()``.

Concrete implementations live in ``rcpond.tools``.

Example use
-----------

>>> class MyTool(Tool):
...     @property
...     def name(self) -> str:
...         return "my_tool"
...
...     @property
...     def description(self) -> str:
...         return "Does something."
...
...     def to_openai_dict(self) -> dict: ...
...     def execute(self, service_now, ticket, **kwargs) -> None: ...

"""

from abc import ABC, abstractmethod

from rcpond.servicenow import FullTicket, ServiceNow

## --------------------------------------------------------------------------------
## Tool ABC


class Tool(ABC):
    """Abstract base class for an LLM tool.

    Subclasses define their own schema (``to_openai_dict``) and execution logic
    (``execute``). The ``name`` and ``description`` properties drive both the
    schema and tool-call dispatch in ``command.py``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The function name exposed to the LLM."""

    @property
    @abstractmethod
    def description(self) -> str:
        """The human-readable description exposed to the LLM."""

    @abstractmethod
    def to_openai_dict(self) -> dict:
        """Return this tool's schema in OpenAI function-calling format.

        Returns
        -------
        dict
            A dict suitable for the ``tools`` parameter of the chat completions API.
        """

    @abstractmethod
    def execute(self, service_now: ServiceNow, ticket: FullTicket, **kwargs) -> None:
        """Execute this tool's action.

        Parameters
        ----------
        service_now : ServiceNow
            The ServiceNow client used to perform the action.
        ticket : FullTicket
            The ticket the action should be applied to.
        **kwargs
            Arguments supplied by the LLM.
        """

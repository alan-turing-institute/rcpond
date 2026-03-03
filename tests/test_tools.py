from unittest.mock import MagicMock

import pytest

from rcpond.servicenow import Ticket
from rcpond.tools import _IMPLEMENTATIONS, Tool, call_tool, get_available_tools

# --- Tool class ---


def test_tool_init():
    def demo_func(a: int, b: str) -> tuple[int, str]:
        """A demo function for testing"""
        return (a, b)

    tool = Tool(demo_func)

    assert tool.name == "demo_func"
    assert tool.description == "A demo function for testing"

    assert tool.parameters == {"a": int, "b": str}


def test_tool_to_openai_dict():
    def my_tool(note: str, count: int) -> None:  # noqa: ARG001
        """Does a thing."""

    tool = Tool(my_tool)
    result = tool.to_openai_dict()

    assert result["type"] == "function"
    assert result["function"]["name"] == "my_tool"
    assert result["function"]["description"] == "Does a thing."
    params = result["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["note"] == {"type": "string"}
    assert params["properties"]["count"] == {"type": "integer"}
    assert set(params["required"]) == {"note", "count"}


# --- get_available_tools ---


def test_get_available_tools_returns_one_tool():
    tools = get_available_tools()
    assert len(tools) == 1
    assert tools[0].name == "_post_note"


def test_get_available_tools_post_note_schema():
    tools = get_available_tools()
    openai_dict = tools[0].to_openai_dict()
    params = openai_dict["function"]["parameters"]
    assert "note" in params["properties"]
    assert params["properties"]["note"] == {"type": "string"}


# --- call_tool ---


def test_call_tool_dispatches_post_note():
    service_now = MagicMock()
    ticket = Ticket(
        sys_id="abc",
        number="RES001",
        opened_at="01/01/2025 09:00:00",
        requested_for="Alice",
        u_category="RC",
        u_sub_category="Azure",
        short_description="Request access",
    )
    planned_tool_call = {
        "function": {
            "name": "_post_note",
            "arguments": {"note": "Please provide more information."},
        }
    }

    call_tool(planned_tool_call, service_now, ticket)

    service_now.post_note.assert_called_once_with(ticket, note="Please provide more information.")


def test_all_tools_have_implementations():
    # Every schema stub in get_available_tools must have a matching entry in _IMPLEMENTATIONS.
    tools = get_available_tools()
    for tool in tools:
        assert tool.name in _IMPLEMENTATIONS, f"No implementation for tool {tool.name!r}"


def test_call_tool_unknown_tool_raises():
    service_now = MagicMock()
    ticket = MagicMock()
    planned_tool_call = {
        "function": {
            "name": "nonexistent_tool",
            "arguments": {},
        }
    }

    with pytest.raises(ValueError, match="nonexistent_tool"):
        call_tool(planned_tool_call, service_now, ticket)

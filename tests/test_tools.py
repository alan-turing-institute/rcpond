from rcpond.tools import Tool


def test_tool_init():

    def demo_func(a: int, b: str) -> tuple[int, str]:
        """A demo function for testing"""
        return (a, b)

    tool = Tool(demo_func)

    assert tool.name == "demo_func"
    assert tool.description == "A demo function for testing"

    assert tool.parameters == {
        "a" : int,
        "b" : str
    }

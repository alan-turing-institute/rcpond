"""Tool definitions available to the LLM and execution of planned tool calls."""

@dataclass
class Tool:
    name: str
    function: callable
    parameters: dict

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

def process_planned_tool_call(planned_tool_call: dict) -> None:
    """Execute a tool call planned by the LLM.

    Parameters
    ----------
    planned_tool_call : dict
        The tool call from the LLM response to execute.
    """
    # Determine which tool is being called
    # Execute the appropriate tool with the provided arguments

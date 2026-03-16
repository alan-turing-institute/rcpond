"""High-level commands for rcpond: listing, processing, and batch-processing tickets.

The four main entry points are:

- `display_all_tickets`: List unassigned tickets from ServiceNow.
- `process_next_ticket`: Review one arbitrarily chosen ticket via the LLM.
- `process_specific_ticket`: Review a given ticket via the LLM.
- `batch_process_tickets`: Review all unassigned tickets via the LLM.
"""

from pprint import pprint

from rcpond.config import Config
from rcpond.llm import LLM, LLMResponse
from rcpond.prompt import construct_prompt
from rcpond.servicenow import FullTicket, ServiceNow, Ticket
from rcpond.tools import call_tool, get_available_tools


def _display_output(*stuff):
    """
    Display stuff in a useful way to the user. Precise behaviour TBD.

    Params:
        stuff: undefined things to display to the user. Precise syntax and structure TBD.
    """

    pprint(stuff)


def _process_ticket(ticket: Ticket, dry_run: bool, config: Config, service_now: ServiceNow, llm: LLM) -> None:
    """Core logic for processing a single ticket via the LLM.

    Fetches full ticket details, constructs the prompt, calls the LLM, and
    optionally executes any planned tool call.

    Parameters
    ----------
    ticket : Ticket
        The ticket to process.
    dry_run : bool
        If True, planned tool calls are not executed.
    config : Config
        The loaded configuration.
    service_now : ServiceNow
        The ServiceNow client.
    llm : LLM
        The LLM client.
    """
    full_ticket: FullTicket = service_now.get_full_ticket(ticket)
    tools = get_available_tools()
    system_prompt, user_prompt = construct_prompt(full_ticket, config)
    llm_response: LLMResponse = llm.generate(
        system_prompt, user_prompt, config.llm_model, tools=[t.to_openai_dict() for t in tools]
    )
    if not dry_run and llm_response.planned_tool_call is not None:
        call_tool(llm_response.planned_tool_call, service_now, full_ticket)
    _display_output(llm_response)


## --------------------------------------------------------------------------------
## Interface to this module


def display_all_tickets(config: Config | None = None):
    """Display the list of unassigned tickets from ServiceNow to the user."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    _display_output(service_now.get_tickets())


def display_single_ticket(ticket_number: str, config: Config | None = None):
    """Display the list of unassigned tickets from ServiceNow to the user."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    all_tkts = service_now.get_tickets()
    _tkts = [t for t in all_tkts if t.number == ticket_number]

    if len(_tkts) == 1:
        # Expected if there is an exact match
        _display_output(service_now.get_full_ticket(_tkts[0]))
    elif len(_tkts) == 0:
        # No match
        err_msg = f"Unable to find ticket number '{ticket_number}'"
        raise ValueError(err_msg)
    else:
        # Unexpected. ServiceNow should prevent this, but just in case
        err_msg = f"Multiple tickets match ticket number '{ticket_number}'\n" "\n\n".join([str(t) for t in _tkts])
        raise ValueError(err_msg)


def process_next_ticket(dry_run: bool, config: Config | None = None):
    """Process an arbitrarily selected ServiceNow ticket via the LLM.

    The LLM response and reasoning are displayed to the user. If the LLM
    recommends an action and ``dry_run`` is False, the action is performed.

    Parameters
    ----------
    dry_run : bool
        If True, planned tool calls are not executed.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    tickets: list[Ticket] = service_now.get_tickets()
    _process_ticket(tickets.pop(), dry_run, config, service_now, llm)


def process_specific_ticket(ticket_number: str, dry_run: bool, config: Config | None = None):
    """Process the given ServiceNow ticket via the LLM.

    The LLM response and reasoning are displayed to the user. If the LLM
    recommends an action and ``dry_run`` is False, the action is performed.

    Parameters
    ----------
    ticket_number : str
        The ticket number (e.g. ``"RES0001234"``) to process.
    dry_run : bool
        If True, planned tool calls are not executed.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    tickets = service_now.get_tickets(include_assigned_tickets=True)
    matched = [t for t in tickets if t.number == ticket_number]
    if not matched:
        msg = f"Ticket '{ticket_number}' not found."
        raise ValueError(msg)
    _process_ticket(matched[0], dry_run, config, service_now, llm)


def batch_process_tickets(dry_run: bool, config: Config | None = None):
    """Process all unassigned ServiceNow tickets via the LLM.

    Each ticket is reviewed individually. The LLM response and reasoning are
    displayed for each. If the LLM recommends actions and ``dry_run`` is False,
    the actions are performed.

    Parameters
    ----------
    dry_run : bool
        If True, planned tool calls are not executed.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    for ticket in service_now.get_tickets():
        _process_ticket(ticket, dry_run, config, service_now, llm)

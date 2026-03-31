"""High-level commands for rcpond: listing, processing, and batch-processing tickets.

The four main entry points are:

- `display_all_tickets`: List unassigned tickets from ServiceNow.
- `process_next_ticket`: Review one arbitrarily chosen ticket via the LLM.
- `process_specific_ticket`: Review a given ticket via the LLM.
- `batch_process_tickets`: Review all unassigned tickets via the LLM.
- `batch_evaluate_tickets`: Evaluate LLM performance against pre-downloaded HTML tickets.
  Requires the ``html`` optional dependency group (``pip install rcpond[html]``).
"""

import json
from pathlib import Path
from pprint import pprint

from rcpond.config import Config
from rcpond.llm import LLM, LLMResponse
from rcpond.prompt import construct_prompt
from rcpond.servicenow import FullTicket, ServiceNow, Ticket
from rcpond.tools import get_available_tools


def _display_output(*stuff):
    """
    Display stuff in a useful way to the user. Precise behaviour TBD.

    Params:
        stuff: undefined things to display to the user. Precise syntax and structure TBD.
    """

    pprint(stuff)


def _process_ticket(ticket: Ticket, dry_run: bool, config: Config, service_now: ServiceNow, llm: LLM) -> LLMResponse:
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
    llm_response: LLMResponse = llm.generate(system_prompt, user_prompt, config.llm_model, tools=tools)
    if not dry_run and llm_response.planned_tool_call is not None:
        name = llm_response.planned_tool_call["function"]["name"]
        args = llm_response.planned_tool_call["function"]["arguments"]
        matched = [t for t in tools if t.name == name]
        if not matched:
            msg = f"Unknown tool: {name!r}"
            raise ValueError(msg)
        matched[0].execute(service_now, full_ticket, **args)

    return llm_response


## --------------------------------------------------------------------------------
## Interface to this module


def display_all_tickets(include_assigned_tickets: bool, config: Config | None = None):
    """Display the list of unassigned tickets from ServiceNow to the user."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    _display_output(service_now.get_tickets(include_assigned_tickets=include_assigned_tickets))


def display_single_ticket(ticket_number: str, config: Config | None = None):
    """Display the details of a specific ticket."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ticket = service_now.get_ticket(ticket_number)
    _display_output(service_now.get_full_ticket(ticket))


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
    resp: LLMResponse = _process_ticket(tickets.pop(), dry_run, config, service_now, llm)
    _display_output(resp)


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
    ticket = service_now.get_ticket(ticket_number)
    _process_ticket(ticket, dry_run, config, service_now, llm)


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
        _ = _process_ticket(ticket, dry_run, config, service_now, llm)


def batch_evaluate_tickets(in_dir: Path, out_file: Path, config: Config | None = None):
    """Process all tickets in an offline html-based directory of ServiceNow tickets.

    Used for evaluating the performance of the LLM in reviewing tickets.

    Parameters
    ----------
    in_dir : Path
        Directory containing pre-downloaded HTML ticket files.
    out_file : Path
        Path to write the JSON results. Must not already exist.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    try:
        from rcpond.html_servicenow import HtmlServiceNow
    except ImportError as e:
        msg = "The 'html' optional dependencies are required for this command. Install them with: pip install rcpond[html]"
        raise ImportError(msg) from e

    if not in_dir.exists():
        msg = f"Input directory does not exist: {in_dir}"
        raise FileNotFoundError(msg)
    if not in_dir.is_dir():
        msg = f"Input path is not a directory: {in_dir}"
        raise NotADirectoryError(msg)
    if not any(in_dir.glob("*.html")):
        msg = f"No .html files found in: {in_dir}"
        raise ValueError(msg)
    if not out_file.parent.exists():
        msg = f"Output directory does not exist: {out_file.parent}"
        raise FileNotFoundError(msg)
    if out_file.exists():
        msg = f"Output file already exists: {out_file}"
        raise FileExistsError(msg)

    config = config or Config()
    service_now: HtmlServiceNow = HtmlServiceNow(in_dir)
    llm: LLM = LLM(config)
    all_responses: list[LLMResponse] = []
    print("DEBUG: service_now.get_tickets(include_assigned_tickets=True)")
    all_tickets = service_now.get_tickets(include_assigned_tickets=True)
    for ticket in all_tickets:
        resp = _process_ticket(ticket=ticket, dry_run=True, config=config, service_now=service_now, llm=llm)
        pprint(f"TICKET: {ticket.number}")
        pprint(resp)
        print()

        all_responses.append(resp)

    with open(out_file, "w") as f:
        json.dump([vars(r) for r in all_responses], f, indent=2)

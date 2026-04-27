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
from rcpond.display import display_full_ticket, display_multi_tickets
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
    print(f"{full_ticket=}")
    tools = get_available_tools(config)
    system_prompt, user_prompt = construct_prompt(full_ticket, config)
    llm_response: LLMResponse = llm.generate(
        system_prompt, user_prompt, config.llm_model, tools=tools, ticket_number=ticket.number
    )
    print(f"{llm_response=}")

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
    display_multi_tickets(service_now.get_tickets(include_assigned_tickets=include_assigned_tickets))


def display_single_ticket(ticket_number: str, config: Config | None = None):
    """Display the details of a specific ticket."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ticket = service_now.get_ticket(ticket_number)
    # _display_output(service_now.get_full_ticket(ticket))
    display_full_ticket(service_now.get_full_ticket(ticket))


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


def batch_evaluate_tickets(in_dir: Path, out_file: Path, num_runs: int = 1, config: Config | None = None):
    """Process all Azure tickets in an offline HTML directory, across multiple runs.

    Used for evaluating the performance of the LLM in reviewing tickets. Results
    are written as ``dict[str, list[LLMResponse]]`` keyed by ticket number, so
    that each ticket's responses across all runs are grouped together. Non-Azure
    tickets are skipped.

    Parameters
    ----------
    in_dir : Path
        Directory containing pre-downloaded HTML ticket files.
    out_file : Path
        Path to write the JSON results. Must not already exist.
    num_runs : int
        Number of times to run the LLM over all tickets (for majority-vote analysis).
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    try:
        from rcpond.html_servicenow import HtmlServiceNow
    except ImportError as e:
        msg = "The 'html' optional dependencies are required for this command. Install them with: pip install rcpond[html]"
        raise ImportError(msg) from e

    config = config or Config()
    service_now: HtmlServiceNow = HtmlServiceNow(in_dir)
    llm: LLM = LLM(config)

    ## Pre-filter to Azure tickets only
    all_tickets = service_now.get_tickets(include_assigned_tickets=True)
    azure_tickets = []
    for ticket in all_tickets:
        # TODO: Temporary, an messy way to limit tickets to only those related to Azure
        # Find a better solution
        full_ticket = service_now.get_full_ticket(ticket)
        if full_ticket.which_service != "Azure":
            print(f"skipping non-Azure ticket: {ticket.number}")
        else:
            azure_tickets.append(ticket)

    ## Run the LLM num_runs times, accumulating responses per ticket
    results: dict[str, list[LLMResponse]] = {t.number: [] for t in azure_tickets}
    for run in range(num_runs):
        print(f"\n--- Run {run + 1}/{num_runs} ---")
        for ticket in azure_tickets:
            resp = _process_ticket(ticket=ticket, dry_run=True, config=config, service_now=service_now, llm=llm)
            results[ticket.number].append(resp)
            print()

    with open(out_file, "w") as f:
        json.dump({k: [vars(r) for r in v] for k, v in results.items()}, f, indent=2)

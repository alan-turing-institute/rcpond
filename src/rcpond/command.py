"""High-level commands for rcpond: listing, processing, and batch-processing tickets.

The four main entry points are:

- `display_all_tickets`: List unassigned tickets from ServiceNow.
- `process_next_ticket`: Review one arbitrarily chosen ticket via the LLM.
- `process_specific_ticket`: Review a given ticket via the LLM.
- `batch_process_tickets`: Review all unassigned tickets via the LLM.
- `batch_evaluate_tickets`: Evaluate LLM performance against pre-downloaded HTML tickets.
  Requires the ``html`` optional dependency group (``uv sync --extra html``).
- `check_templates`: Render all Jinja2 templates in a directory with dummy variable values (for CI).
- `dump_tickets`: Write every ticket of every registered type to a jsonl dump file.
"""

import json
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from rich import print

from rcpond.config import Config
from rcpond.display import (
    display_compute_allocation_request_ticket,
    display_github_leavers_request_ticket,
    display_github_onboarding_request_ticket,
    display_multi_tickets,
    display_related_tickets,
    display_response,
    display_short_ticket,
)
from rcpond.llm import LLM, LLMResponse
from rcpond.prompt import construct_prompt
from rcpond.servicenow import (
    ComputeAllocationRequestTicket,
    GitHubOnboardingRequestTicket,
    RelatedTicketMatch,
    ResearchLeaversGitHubTicket,
    ServiceNow,
    Ticket,
    TicketState,
    all_registered_types_query,
)
from rcpond.ticket_dumps import write_dump
from rcpond.tools import CombineTicketHistoryTool, get_available_tools, verify_render_all_templates

if TYPE_CHECKING:
    ## Imported lazily inside analytics(): analytics.py requires the optional ``html``
    ## dependency group (pandas + tabulate), which the rest of the package does not need.
    from rcpond.analytics import Period


class ReplyMode(str, Enum):
    """Controls which tickets _process_ticket will skip.

    cautious: skip if RCPond has ever posted on the ticket.
    default:  skip only when RCPond's comment or work note is the most recent activity.
    always:   never skip regardless of ticket state.
    """

    cautious = "cautious"
    default = "default"
    always = "always"


## Maximum number of LLM turns before the loop is forcibly exited.
_MAX_ITERATIONS = 3

## Derived from the tool itself so the two cannot drift apart.
_COMBINE_TICKET_HISTORY = CombineTicketHistoryTool().name


def _should_skip(full_ticket: Ticket, reply_mode: ReplyMode) -> bool:
    """Return True if the ticket should be skipped given the reply mode."""
    ## Never skip if the most recent RCPond note is a CombineTicketHistory audit —
    ## the expected follow-up response has not yet been posted.
    if full_ticket.rcpond_most_recent_tool_name() == _COMBINE_TICKET_HISTORY:
        return False
    if reply_mode == ReplyMode.cautious:
        return full_ticket.is_rcpond_processed()
    if reply_mode == ReplyMode.default:
        return full_ticket.is_rcpond_most_recent_process()
    return False  ## always


def _concurrent_skip_response(
    full_ticket: Ticket, service_now: ServiceNow, reply_mode: ReplyMode, dry_run: bool
) -> LLMResponse | None:
    """Re-check for concurrent activity before committing a write.

    Refreshes the ticket and, if another party has posted since processing began,
    returns a deterministic skip ``LLMResponse``; otherwise returns ``None``. In a
    dry run nothing is written, so there is no race to guard against and ``None`` is
    returned without a refresh. Keeping the dry-run guard here means ``_process_ticket``
    needs no ``dry_run`` branching of its own.

    Parameters
    ----------
    full_ticket : Ticket
        The ticket being processed; refreshed in place when not a dry run.
    service_now : ServiceNow
        The ServiceNow client used to refresh the ticket.
    reply_mode : ReplyMode
        Controls when concurrent activity counts as a reason to skip.
    dry_run : bool
        When True, no write will occur, so the check is skipped.

    Returns
    -------
    LLMResponse | None
        A skip response if processing should be abandoned, else ``None``.
    """
    if dry_run:
        return None
    full_ticket.refresh(service_now)
    if not _should_skip(full_ticket, reply_mode):
        return None
    prev_msg = full_ticket.get_combined_notes()[-1]
    msg = f"Skipping: Another user has commented on ticket '{full_ticket.number}' whilst RCPond was working. Their message is\n'{prev_msg}'"
    return LLMResponse(
        response_text="",
        reasoning=msg,
        planned_tool_call=None,
        ticket_number=full_ticket.number,
        llm_model=None,
    )


def _process_ticket(
    ticket: Ticket,
    dry_run: bool,
    config: Config,
    service_now: ServiceNow,
    llm: LLM,
    reply_mode: ReplyMode,
) -> LLMResponse:
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
    reply_mode : ReplyMode
        Controls when to skip a ticket based on prior RCPond activity.
        See ``ReplyMode`` for the options.
    """
    full_ticket = service_now.get_full_ticket(ticket)
    if _should_skip(full_ticket, reply_mode):
        prev_time = full_ticket.get_combined_notes()[-1].datetime_stamp
        msg = f"Skipping: There has been no new activity on ticket '{full_ticket.number}' since RCPond's previous review on {prev_time}"
        ## llm_model=None signals a deterministic (non-LLM) response
        return LLMResponse(
            response_text="", reasoning=msg, planned_tool_call=None, ticket_number=full_ticket.number, llm_model=None
        )

    tools = get_available_tools(config)
    system_prompt, user_prompt = construct_prompt(full_ticket, config)
    extra_messages: list[dict] = []

    for _ in range(_MAX_ITERATIONS):
        llm_response = llm.generate(
            system_prompt,
            user_prompt,
            config.llm_model,
            tools=tools,
            ticket_number=ticket.number,
            extra_messages=extra_messages or None,
        )

        if llm_response.planned_tool_call is None:
            ## Text response — abandon if another party posted while we were working.
            if (skip := _concurrent_skip_response(full_ticket, service_now, reply_mode, dry_run)) is not None:
                return skip
            break

        name = llm_response.planned_tool_call["function"]["name"]
        args = llm_response.planned_tool_call["function"]["arguments"]
        matched = [t for t in tools if t.name == name]
        if not matched:
            msg = f"Unknown tool: {name!r}"
            raise ValueError(msg)
        tool = matched[0]

        ## Each tool honours dry_run internally (suppressing any ServiceNow writes),
        ## so the loop itself never branches on dry_run.
        if tool.is_terminal:
            ## Terminal tools commit a final note; abandon first if another party posted.
            if (skip := _concurrent_skip_response(full_ticket, service_now, reply_mode, dry_run)) is not None:
                return skip
            tool.execute(service_now, full_ticket, dry_run=dry_run, **args)
            break

        ## Non-terminal: execute, inject the result into the next LLM turn, and continue.
        result = tool.execute(service_now, full_ticket, dry_run=dry_run, **args)
        tool_call = llm_response.planned_tool_call
        extra_messages += [
            {
                "role": "assistant",
                "content": llm_response.response_text or "",
                "tool_calls": [
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result or "",
            },
        ]

    return llm_response


## --------------------------------------------------------------------------------
## Interface to this module


def check_templates(config: Config) -> bool:
    """Render all non-partial Jinja2 templates in a directory with dummy variable values.

    Delegates to ``PostTemplatedNoteTool.render_all`` so the same rendering code
    path used in production is exercised. Intended for use as a CI check in the
    templates repository.

    Parameters
    ----------
    templates_dir : Path
        Directory containing ``*.j2`` template files. Files whose names start
        with ``_`` are treated as partials and not rendered directly.

    Returns
    -------
    bool
        True if every top-level template renders without error; False otherwise.
        A pass/fail line is printed for each template.
    """
    results = verify_render_all_templates(config)
    for name, passed, error in results:
        if passed:
            print(f"  [green]PASS[/green]  {name}")
        else:
            print(f"  [red]FAIL[/red]  {name}: {error}")
    return all(passed for _, passed, _ in results)


def display_all_tickets(state: TicketState = TicketState.user_focus, config: Config | None = None):
    """Display tickets from ServiceNow filtered by state."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    display_multi_tickets(service_now.get_tickets(state=state))


def display_single_ticket(ticket_number: str, config: Config | None = None):
    """Display the details of a specific ticket."""
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ticket = service_now.get_ticket(ticket_number)
    full_ticket = service_now.get_full_ticket(ticket)

    match full_ticket:
        case ComputeAllocationRequestTicket():
            display_compute_allocation_request_ticket(full_ticket)
        case GitHubOnboardingRequestTicket():
            display_github_onboarding_request_ticket(full_ticket)
        case ResearchLeaversGitHubTicket():
            display_github_leavers_request_ticket(full_ticket)
        case _:
            err_msg = f"unknown ticket type {type(full_ticket)}"
            raise ValueError(err_msg)


def get_ticket_url(ticket_number: str, config: Config | None = None) -> str:
    """Return the ServiceNow Web UI URL for a specific ticket.

    Parameters
    ----------
    ticket_number : str
        The ticket number to look up (e.g. ``"RES0001234"``).
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ticket = service_now.get_ticket(ticket_number)
    return service_now.web_url(ticket)


def find_related_tickets(ticket_number: str, config: Config | None = None) -> list[RelatedTicketMatch]:
    """Find tickets related to the given ticket number using field-matching heuristics.

    Parameters
    ----------
    ticket_number : str
        The ticket to search from (e.g. ``"RES0001234"``).
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.

    Returns
    -------
    list[RelatedTicketMatch]
        Related tickets and the heuristics that matched.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ticket = service_now.get_ticket(ticket_number)
    full_ticket = service_now.get_full_ticket(ticket)
    matches = service_now.find_related_tickets(full_ticket)
    display_related_tickets(full_ticket, matches)
    return matches


def default_dump_filename(servicenow_web_url: str, now: datetime | None = None) -> str:
    """Return the default ``dump-tickets`` filename for an instance.

    ``<web-domain>_<YYYYmmddTHHMMSS>.jsonl`` in local time. Colons are deliberately absent:
    unlike the header's ``created_at``, this has to be a valid filename on every platform.

    Parameters
    ----------
    servicenow_web_url : str
        The configured ServiceNow web UI URL; its domain names the instance.
    now : datetime | None
        Timestamp to use, defaulting to the local time now.

    Returns
    -------
    str
        The filename, without any directory part.
    """
    domain = urlparse(servicenow_web_url).netloc or "unknown-instance"
    stamp = (now or datetime.now()).strftime("%Y%m%dT%H%M%S")  # - local time, by design
    return f"{domain}_{stamp}.jsonl"


def dump_tickets(out_file: Path | None = None, limit: int | None = None, config: Config | None = None) -> Path:
    """Dump every ticket of every registered type to a jsonl file.

    Fetches the base tickets in one bulk call, then the full ticket — including the
    catalogue variables — one request at a time. That fan-out is the expensive part, taking
    around 70 seconds against the production instance, so progress is reported as it goes.

    Parameters
    ----------
    out_file : Path | None
        Where to write. Defaults to ``default_dump_filename()`` in the current directory.
    limit : int | None
        Dump only the first ``limit`` tickets by ticket number. Sampling aid: the result is
        a deliberately partial dump, recorded as such in the file's header.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.

    Returns
    -------
    Path
        The file written.

    Raises
    ------
    ValueError
        If the output file already exists, or its directory does not.
    Exception
        Whatever a failed ticket fetch raised, with the ticket number added. No file is
        written: a dump missing tickets would be indistinguishable from a complete one.
    """
    config = config or Config()

    path = Path(out_file) if out_file is not None else Path.cwd() / default_dump_filename(config.servicenow_web_url)
    ## Both checks precede the query. The fan-out takes ~70sec, and discovering the path is
    ## unusable after it would waste the whole run.
    if path.exists():
        msg = f"Output file already exists: {path}. Delete it, or choose a different --output-file."
        raise ValueError(msg)
    if not path.parent.is_dir():
        msg = f"Output directory does not exist: {path.parent}"
        raise ValueError(msg)

    service_now: ServiceNow = ServiceNow(config)
    query = all_registered_types_query()
    ## The configured query is a single type's, so without the explicit cross-type query the
    ## dump would silently hold only that type.
    tickets = service_now.get_tickets(state=TicketState.all_including_closed, query=query)

    ## Sort before slicing, not merely before writing: it is what makes --limit reproducible,
    ## since ServiceNow's result order is not guaranteed stable between runs.
    tickets = sorted(tickets, key=lambda t: t.number)
    if limit is not None:
        tickets = tickets[:limit]

    full_tickets: list[Ticket] = []
    for num, ticket in enumerate(tickets, start=1):
        try:
            full_tickets.append(service_now.get_full_ticket(ticket))
        except Exception as exc:
            ## Abort rather than skip: a skipped ticket would make record_count under-count,
            ## leaving a quietly partial dump. Re-raised with the ticket named rather than
            ## annotated via add_note, because notes do not appear in str(exc) and the CLI
            ## prints exactly that — the context would be lost where it is most needed.
            msg = (
                f"Failed to fetch full details for ticket {ticket.number} "
                f"({num} of {len(tickets)}): {exc!r}. No dump was written."
            )
            raise RuntimeError(msg) from exc
        ## One rewritten line, so a long run does not look hung. Written straight to
        ## stdout, not via rich's print: rich strips the carriage return, so every update
        ## would append instead of overwriting — 73 counters on one line for 731 tickets.
        if num % 10 == 0 or num == len(tickets):
            sys.stdout.write(f"\r  {num}/{len(tickets)} tickets")
            sys.stdout.flush()
    sys.stdout.write("\n")

    write_dump(
        path,
        full_tickets,
        servicenow_url=config.servicenow_url,
        servicenow_web_url=config.servicenow_web_url,
        query=query,
        limit=limit,
    )
    return path


def analytics(config: Config | None = None, refresh: bool = False, period: "Period | None" = None) -> str:
    """Generate the RCPond analytics report as markdown, print it, and return it.

    Fetches all tickets in every state (including closed, resolved, and cancelled)
    in a single bulk call, builds a one-row-per-ticket DataFrame, renders the markdown
    report, writes it to stdout verbatim (so it can be redirected to a ``.md`` file),
    and returns it.

    Requires the optional ``html`` dependency group (``uv sync --extra html``);
    ``rcpond.analytics`` is imported lazily so the rest of the package works without it.

    Parameters
    ----------
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    refresh : bool
        Reserved for the future ticket-history cache. The cache is not yet
        implemented — a single bulk fetch is currently optimal — so this flag has
        no effect today.
    period : Period | None
        Granularity for the over-time trends section (month, quarter, or year).
        Defaults to ``Period.quarter`` when not given.

    Returns
    -------
    str
        The markdown report.
    """
    from rcpond.analytics import Period, build_ticket_frame, render_markdown

    ## TODO: --refresh becomes meaningful once a stage needs per-ticket full fetches
    ## and the ticket-history cache (see planning/analytics.md) is implemented.
    _ = refresh
    period = period or Period.quarter
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    ## Analytics reports per ticket type, so it must fetch every type. The configured
    ## query belongs to a single type (or falls back to the default type's), which would
    ## silently narrow the report to that one type.
    tickets = service_now.get_tickets(
        state=TicketState.all_including_closed,
        query=all_registered_types_query(),
    )
    report = render_markdown(build_ticket_frame(tickets), period)
    ## Write verbatim (not via rich.print, which would wrap/format the markdown table).
    sys.stdout.write(report)
    return report


def process_next_ticket(dry_run: bool, reply_mode: ReplyMode, config: Config | None = None):
    """Process an arbitrarily selected ServiceNow ticket via the LLM.

    The LLM response and reasoning are displayed to the user. If the LLM
    recommends an action and ``dry_run`` is False, the action is performed.

    Parameters
    ----------
    dry_run : bool
        If True, planned tool calls are not executed.
    reply_mode : ReplyMode
        Controls when to skip a ticket based on prior RCPond activity.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    tickets: list[Ticket] = service_now.get_tickets()
    next_ticket = tickets.pop()
    resp: LLMResponse = _process_ticket(next_ticket, dry_run, config, service_now, llm, reply_mode)
    display_short_ticket(next_ticket)
    display_response(resp)


def process_specific_ticket(ticket_number: str, dry_run: bool, reply_mode: ReplyMode, config: Config | None = None):
    """Process the given ServiceNow ticket via the LLM.

    The LLM response and reasoning are displayed to the user. If the LLM
    recommends an action and ``dry_run`` is False, the action is performed.

    Parameters
    ----------
    ticket_number : str
        The ticket number (e.g. ``"RES0001234"``) to process.
    dry_run : bool
        If True, planned tool calls are not executed.
    reply_mode : ReplyMode
        Controls when to skip a ticket based on prior RCPond activity.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    ticket = service_now.get_ticket(ticket_number)
    resp: LLMResponse = _process_ticket(ticket, dry_run, config, service_now, llm, reply_mode)
    display_short_ticket(ticket)
    display_response(resp)


def batch_process_tickets(dry_run: bool, reply_mode: ReplyMode, config: Config | None = None):
    """Process all unassigned ServiceNow tickets via the LLM.

    Each ticket is reviewed individually. The LLM response and reasoning are
    displayed for each. If the LLM recommends actions and ``dry_run`` is False,
    the actions are performed.

    Parameters
    ----------
    dry_run : bool
        If True, planned tool calls are not executed.
    reply_mode : ReplyMode
        Controls when to skip a ticket based on prior RCPond activity.
    config : Config | None
        Configuration to use. If None, Config() is constructed from the environment.
    """
    config = config or Config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)
    all_tickets = service_now.get_tickets()

    if len(all_tickets) > 0:
        for num, ticket in enumerate(all_tickets, start=1):
            print(f"Processing ticket {num} of {len(all_tickets)}")
            resp: LLMResponse = _process_ticket(ticket, dry_run, config, service_now, llm, reply_mode)
            display_short_ticket(ticket)
            display_response(resp)
    else:
        print("No tickets that have not been previously processed by RCPond")


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
    all_tickets = service_now.get_tickets(state=TicketState.all_open)
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
            resp = _process_ticket(
                ticket=ticket,
                dry_run=True,
                config=config,
                service_now=service_now,
                llm=llm,
                reply_mode=ReplyMode.always,
            )
            results[ticket.number].append(resp)
            print()

    with open(out_file, "w") as f:
        json.dump({k: [vars(r) for r in v] for k, v in results.items()}, f, indent=2)

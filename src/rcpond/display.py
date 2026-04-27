"""Display functions for rcpond output.

Provides:

- `display_all_tickets`: Display a grouped summary table of tickets.
- `display_ticket`: Display a high-level ticket summary.
- `display_full_ticket`: Display the full details of a ticket.
- `display_response`: Display an LLM response.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from rcpond.llm import LLMResponse
from rcpond.servicenow import FullTicket, Ticket

_console = Console()

## --------------------------------------------------------------------------------
## Internal helpers


def _kv_table(rows: list[tuple[str, str]], *, min_col_width: int = 30) -> Table:
    """Build a two-column key/value table with no visible borders."""
    table = Table(show_header=False, box=None, padding=(0, 1), min_width=min_col_width)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for key, value in rows:
        table.add_row(key, value or "[dim]—[/dim]")
    return table


def _section(title: str, rows: list[tuple[str, str]]) -> Panel:
    """Wrap a key/value table in a titled panel."""
    return Panel(_kv_table(rows), title=f"[bold]{title}[/bold]", title_align="left", border_style="dim")


## --------------------------------------------------------------------------------
## Public API


def _header_panel(ticket: Ticket) -> Panel:
    """Build the header panel shared by display_ticket and display_full_ticket."""
    header = _kv_table(
        [
            ("Number", ticket.number),
            ("Opened", ticket.opened_at),
            ("Requested by", ticket.requested_for),
            ("Category", f"{ticket.u_category} / {ticket.u_sub_category}"),
            ("Description", ticket.short_description),
        ]
    )
    return Panel(
        header, title=f"[bold white]{ticket.number}[/bold white]", title_align="left", border_style="bright_blue"
    )


def display_ticket(ticket: Ticket, *, console: Console | None = None) -> None:
    """Display a high-level ticket summary.

    Parameters
    ----------
    ticket : Ticket
        The ticket to display.
    console : Console | None
        Rich Console to write to. Defaults to the module-level console (stdout).
    """
    con = console or _console
    con.print(_header_panel(ticket))


def display_full_ticket(ticket: FullTicket, *, console: Console | None = None) -> None:
    """Display the full details of a ticket using Rich formatting.

    Parameters
    ----------
    ticket : FullTicket
        The ticket to display.
    console : Console | None
        Rich Console to write to. Defaults to the module-level console (stdout).
    """
    con = console or _console

    con.print(_header_panel(ticket))

    ## Request details
    con.print(
        _section(
            "Request details",
            [
                ("Service", ticket.which_service),
                ("Subscription type", ticket.subscription_type),
                ("New / existing", ticket.new_or_existing_allocation),
                ("Research area", ticket.research_area_programme or ticket.if_other_please_specify),
                ("Data sensitivity", ticket.data_sensitivity),
                ("Start date", ticket.start_date),
                ("End date", ticket.end_date),
            ],
        )
    )

    ## Project
    con.print(
        _section(
            "Project",
            [
                ("Project title", ticket.project_title),
                ("PI / Supervisor", ticket.pi_supervisor_name),
                ("PI email", ticket.pi_supervisor_email),
            ],
        )
    )

    ## Finance
    con.print(
        _section(
            "Finance",
            [
                ("Credits requested", ticket.credits_requested),
                ("Finance code", ticket.which_finance_code),
                ("PMU contact email", ticket.pmu_contact_email),
                ("Subscription / Azure ID", ticket.azure_subscription_id_or_hpc_group_project_id),
                ("Cost breakdown", ticket.cost_compute_time_breakdown),
            ],
        )
    )

    ## Technical requirements
    con.print(
        _section(
            "Technical requirements",
            [
                ("CPU hours", ticket.cpu_hours_required),
                ("GPU hours", ticket.gpu_hours_required),
                ("Facility", ticket.which_facility or ticket.if_other_please_specify_facility),
                ("Computational requirements", ticket.computational_requirements),
                ("Platform justification", ticket.platform_justification),
                ("Research justification", ticket.research_justification),
            ],
        )
    )

    ## Access
    if ticket.users_who_require_access_names_and_emails:
        con.print(
            _section(
                "Users requiring access",
                [
                    ("Users", ticket.users_who_require_access_names_and_emails),
                ],
            )
        )

    ## Work notes
    if ticket.work_notes:
        con.print(
            Panel(
                Text(ticket.work_notes, overflow="fold"),
                title="[bold]Work notes[/bold]",
                title_align="left",
                border_style="dim",
            )
        )


def display_multi_tickets(tickets: list[Ticket], *, console: Console | None = None) -> None:
    """Display a table of ticket summaries.

    Each section represents tickets with common values of "Category" and "Description". The Description field is used for the section title.

    Each row represents a single ticket. It should have the columns
    - Number
    - Opened date/time
    - Requested by
    - Status (new / assigned / on-hold / etc)
    """
    con = console or _console

    if not tickets:
        con.print("[dim]No tickets found.[/dim]")
        return

    ## Group tickets by (u_category, short_description)
    groups: dict[tuple[str, str], list[Ticket]] = {}
    for ticket in tickets:
        key = (ticket.u_category, ticket.short_description)
        groups.setdefault(key, []).append(ticket)

    for (category, description), group in groups.items():
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("Number", no_wrap=True)
        table.add_column("Opened", no_wrap=True)
        table.add_column("Requested by")
        table.add_column("Status")

        for ticket in group:
            table.add_row(
                ticket.number,
                ticket.opened_at,
                ticket.requested_for,
                # ticket.u_sub_category,
                "",  # Pending adding status field
            )

        title = f"[bold]{description} / {category}[/bold]"
        con.print(Panel(table, title=title, title_align="left", border_style="bright_blue"))


def display_response(response: LLMResponse) -> None:
    """Display an LLM response.

    Parameters
    ----------
    response : LLMResponse
        The response to display.
    """
    raise NotImplementedError

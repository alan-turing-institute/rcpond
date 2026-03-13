import typer

from rcpond import command

cli = typer.Typer(name="rcpond")


@cli.command()
def display_all_tickets():
    """List all unassigned tickets from ServiceNow."""
    command.display_all_tickets()


@cli.command()
def process_next(dry_run: bool = False):
    """Review an arbitrarily selected unassigned ticket via the LLM."""
    command.process_next_ticket(dry_run=dry_run)


@cli.command()
def process_ticket(ticket_number: str, dry_run: bool = False):
    """Review a specific ticket (e.g. RES0001234) via the LLM."""
    command.process_specific_ticket(ticket_number=ticket_number, dry_run=dry_run)


@cli.command()
def batch_process(dry_run: bool = False):
    """Review all unassigned tickets via the LLM."""
    command.batch_process_tickets(dry_run=dry_run)

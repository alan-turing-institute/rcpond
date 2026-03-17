"""
CLI for rcpond.

This module creates the Typer `cli` object that is the target of the pyproject.scripts directive.

It adds four subcommands

- `display-all-tickets`
- `process-next`
- `process-ticket`
- `process-all`

Each delegating to the corresponding function in `command.py`.

Configuration is supplied via group-level options (e.g. `--env-file`) that
must appear *before* the subcommand name:

    rcpond --env-file .env display-all-tickets

All config options default to None and fall back to `RCPOND_*` environment
variables and/or any `.env` file supplied.

The `Config` object is constructed via the `_config` helpful func, so that config validation will not be called when using the `--help` option, directly on `rcpond` or one one of the subcommands.
"""

from importlib.metadata import version
from typing import Annotated

import typer
from rich import print

from rcpond import command
from rcpond.config import Config

cli = typer.Typer(name="rcpond", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(version("rcpond"))
        raise typer.Exit()


@cli.callback()
def common_options(
    ctx: typer.Context,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            ## is_eager ensures this runs before subcommand processing (and before Config
            ## validation); expose_value=False keeps it out of ctx.obj.
            is_eager=True,
            expose_value=False,
            callback=_version_callback,
        ),
    ] = False,
    env_file: Annotated[str | None, typer.Option(help="Path to a .env config file.")] = None,
    llm_chat_completions_url: Annotated[str | None, typer.Option(help="LLM API endpoint URL.")] = None,
    llm_api_key: Annotated[str | None, typer.Option(help="LLM API key.")] = None,
    llm_model: Annotated[str | None, typer.Option(help="LLM model identifier.")] = None,
    servicenow_token: Annotated[str | None, typer.Option(help="ServiceNow API token.")] = None,
    servicenow_url: Annotated[str | None, typer.Option(help="ServiceNow API base URL.")] = None,
    rules_path: Annotated[str | None, typer.Option(help="Path to the rules file.")] = None,
    system_prompt_template_path: Annotated[str | None, typer.Option(help="Path to the system prompt template.")] = None,
) -> None:
    ## Store raw args — Config is built lazily in each command so that `--help`` never triggers validation.
    ctx.ensure_object(dict)
    ctx.obj = {
        "env_path": env_file,
        "cli_args": {
            "llm_chat_completions_url": llm_chat_completions_url,
            "llm_api_key": llm_api_key,
            "llm_model": llm_model,
            "servicenow_token": servicenow_token,
            "servicenow_url": servicenow_url,
            "rules_path": rules_path,
            "system_prompt_template_path": system_prompt_template_path,
        },
    }


def _config(ctx: typer.Context) -> Config:
    return Config(env_path=ctx.obj["env_path"], cli_args=ctx.obj["cli_args"])


@cli.command()
def display_all(ctx: typer.Context, include_assigned_tickets: bool = False):
    """Display all unassigned tickets from ServiceNow."""
    command.display_all_tickets(include_assigned_tickets=include_assigned_tickets, config=_config(ctx))


@cli.command()
def display_ticket(ctx: typer.Context, ticket_number: str):
    """Display the details of a specific ticket (e.g. RES0001234)."""
    command.display_single_ticket(ticket_number=ticket_number, config=_config(ctx))


@cli.command()
def process_next(ctx: typer.Context, dry_run: bool = False):
    """Review an arbitrarily selected unassigned ticket via the LLM."""
    command.process_next_ticket(dry_run=dry_run, config=_config(ctx))


@cli.command()
def process_ticket(ctx: typer.Context, ticket_number: str, dry_run: bool = False):
    """Review a specific ticket (e.g. RES0001234) via the LLM."""
    command.process_specific_ticket(ticket_number=ticket_number, dry_run=dry_run, config=_config(ctx))


@cli.command()
def process_all(
    ctx: typer.Context,
    dry_run: bool = False,
    ## Single flag name (no "--flag/--no-flag" form) suppresses Typer's auto-generated
    ## negative, which would otherwise produce the unreadable `--no-yes-i-am-sure`.
    yes_i_am_sure: Annotated[
        bool, typer.Option("--yes-i-am-sure", help="Confirm processing all unassigned tickets.")
    ] = False,
):
    """Review all unassigned tickets via the LLM."""
    if yes_i_am_sure:
        command.batch_process_tickets(dry_run=dry_run, config=_config(ctx))
    else:
        msg = "The [bold cyan]--yes-i-am-sure[/bold cyan] option MUST be specified when using the [bold]process-all[/bold] subcommand."
        print(msg)
        typer.echo(ctx.get_help())

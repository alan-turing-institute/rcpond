# Notes and assumptions
#
# `load_config()` should return either a dict or a data class (TBD)
#
# `construct_prompt()` will need access to the config (in order to get the system
# prompt, prompt template, available tools etc). It is not clear if should be passed
# as a param (example here) or via an enclosing class, or some other means
#
# Here the return value of `llm.process_prompt` is assumed to be a tuple
# (response, reasoning, action_plans). There might be other preferred ways to define
# this (eg as a class or dict etc).
#
# The `ServiceNow` class can either be an abstraction to:
# * The main production ServiceNow instance
# * The development ServiceNow instance
# * A directory of scraped html files
# This could be controlled either by the configuration file/object and/or by using
# subclasses. Once initialised the caller should not have to care about the
# underlying data source


# Assumed import paths
from rcpond.llm import LLM
from rcpond.servicenow import ServiceNow, Ticket
from rcpond.undefined_middle_blob import (
    construct_prompt,
    load_config,
    process_action_plan,
)


def _display_output(*stuff):
    """
    Display stuff in a useful way to the user. Precise behaviour TBD.

    Params:
        stuff: undefined things to display to the user. Precise syntax and structure TBD.
    """


def display_all_tickets(assigned_only: bool):
    """
    Display the list of relevant tickets from ServiceNow to the user.

    Params:
        assigned_only:
            True : only include the tickets that have been assigned to the current individual user
            False : all tickets are "unassigned to an individual" but are "assigned to the current user's
                    assignment group"

    """
    config = load_config()
    service_now: ServiceNow = ServiceNow(config)

    tickets: list[Ticket] = service_now.get_all_tickets(assigned_only)
    _display_output(tickets)


def process_next_ticket(assigned_only: bool, dry_run: bool):
    """
    Processes an arbitrarily selected ServiceNow ticket, reviewing it via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        assigned_only:
            True : only include the tickets that have been assigned to the current individual user
            False : all tickets are "unassigned to an individual" but are "assigned to the current user's
                    assignment group"
        dry_run:
    """
    # This function is very similar to `batch_process_tickets` and probably should be refactored.

    config = load_config()
    service_now: ServiceNow = ServiceNow(config)

    tickets: list[Ticket] = service_now.get_all_tickets(assigned_only)
    next_ticket_id = tickets.pop().ticket_id

    # This stub code here unnecessarily recreates the `llm` and `service_now` objects. This
    # should be fixed as these objects should only need to be created once. However until
    # the structure of the other modules is defined this is not possible.
    process_specific_ticket(next_ticket_id, dry_run)


def process_specific_ticket(ticket_id: str, dry_run: bool):
    """
    Processes the ServiceNow ticket identified by `ticket_id`, reviewing it via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        ticket_id: The ServiceNow ticket number. (ServiceNow uses the field name "Number", but the values are
                   strings - example `RES0001752`)
        dry_run:
            True : Action plans returned by the LLM will NOT be attempted
            False : Action plans returned by the LLM WILL be attempted
    """

    config = load_config()
    service_now: ServiceNow = ServiceNow(config)
    llm: LLM = LLM(config)

    ticket: Ticket = service_now.get_ticket(ticket_id)

    # See note above about how the construct_prompt accesses config
    prompt = construct_prompt(ticket, config)

    # Here `response` = the text generated for the user to read (arguably the whole thing is a "response")
    # If there is a better terminology to distinguish this, then we should adopt that.
    response, reasoning, action_plans = llm.process_prompt(prompt)

    if not dry_run:
        for plan in action_plans:
            process_action_plan(plan)

    _display_output(response, reasoning)


def batch_process_tickets(assigned_only: bool, dry_run: bool):
    """
    Processes all of the available ServiceNow tickets, reviewing each one individually via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        assigned_only:
            True (default) only include the tickets that have been assigned to the current individual user
            False : all tickets are "unassigned to an individual" but are "assigned to the current user's
                    assignment group"
        dry_run:
            True : Action plans returned by the LLM will NOT be attempted
            False : Action plans returned by the LLM WILL be attempted
    """
    # Notes
    #
    # See note about different types of ServiceNow instances

    # This stub code here unnecessarily recreates the `llm` and `service_now` objects. This
    # should be fixed as these objects should only need to be created once. However until
    # the structure of the other modules is defined this is not possible.
    #
    # This function is very similar to `process_next_ticket` and probably should be refactored.

    config = load_config()
    service_now: ServiceNow = ServiceNow(config)

    tickets: list[Ticket] = service_now.get_all_tickets(assigned_only)
    for next_ticket in tickets:
        process_specific_ticket(next_ticket.ticket_id, dry_run)

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
from typing import List

from rcpond.servicenow import ServiceNow, Ticket
from rcpond.llm import LLM
from rcpond.undefined_middle_blob import construct_prompt, load_config, process_action_plan


def _display_output(*stuff):
    pass

def display_all_tickets(assigned_only: bool):
    """
    
    Params:
        assigned_only:
        True (default) only include the tickets that have been assigned to the current individual user
        False : all tickets applied 

    """
    config = load_config()
    service_now : ServiceNow = ServiceNow(config)
    
    tickets: List[Ticket] = service_now.get_all_tickets(assigned_only)
    _display_output(tickets)

def process_next_ticket(assigned_only: bool, dry_run: bool):
    # This function is very similar to `batch_process_tickets` and probably should be refactored.

    config = load_config()
    service_now : ServiceNow = ServiceNow(config)
    
    tickets: List[Ticket] = service_now.get_all_tickets(assigned_only)
    next_ticket_id = tickets.pop().ticket_id

    # This stub code here unnecessarily recreates the `llm` and `service_now` objects. This
    # should be fixed as these objects should only need to be created once. However until 
    # the structure of the other modules is defined this is not possible.
    process_specific_ticket(next_ticket_id, dry_run)


def process_specific_ticket(ticket_id: str, dry_run: bool):

    config = load_config()
    service_now : ServiceNow = ServiceNow(config)
    llm : LLM = LLM(config)

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
    # Notes
    #
    # See note about different types of ServiceNow instances

    # This stub code here unnecessarily recreates the `llm` and `service_now` objects. This
    # should be fixed as these objects should only need to be created once. However until 
    # the structure of the other modules is defined this is not possible.
    #
    # This function is very similar to `process_next_ticket` and probably should be refactored.

    config = load_config()
    service_now : ServiceNow = ServiceNow(config)
    
    tickets: List[Ticket] = service_now.get_all_tickets(assigned_only)
    for next_ticket in tickets:
        process_specific_ticket(next_ticket.ticket_id, dry_run)

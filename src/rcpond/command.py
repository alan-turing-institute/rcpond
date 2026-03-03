# Assumed import paths
from rcpond.config import load_config
from rcpond.llm import LLM, LLMResponse
from rcpond.prompt import construct_prompt
from rcpond.servicenow import FullTicket, ServiceNow, Ticket
from rcpond.tools import call_tool


def _display_output(*stuff):
    """
    Display stuff in a useful way to the user. Precise behaviour TBD.

    Params:
        stuff: undefined things to display to the user. Precise syntax and structure TBD.
    """


def display_all_tickets():
    """
    Display the list of relevant tickets from ServiceNow to the user.

    """
    config = load_config()
    service_now: ServiceNow = ServiceNow(config.servicenow_token)

    tickets: list[Ticket] = service_now.get_unassigned_tickets()
    _display_output(tickets)


def process_next_ticket(dry_run: bool):
    """
    Processes an arbitrarily selected ServiceNow ticket, reviewing it via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        dry_run:
            True : Planned tool calls returned by the LLM will NOT be attempted
            False : Planned tool calls returned by the LLM WILL be attempted
    """
    # This function is very similar to `batch_process_tickets` and probably should be refactored.

    config = load_config()
    service_now: ServiceNow = ServiceNow(config.servicenow_token)

    tickets: list[Ticket] = service_now.get_unassigned_tickets()
    next_ticket = tickets.pop()

    # This stub code here unnecessarily recreates the `llm` and `service_now` objects. This
    # should be fixed as these objects should only need to be created once. However until
    # the structure of the other modules is defined this is not possible.
    process_specific_ticket(next_ticket, dry_run)


def process_specific_ticket(ticket: Ticket, dry_run: bool):
    """
    Processes the ServiceNow ticket identified by `ticket`, reviewing it via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        ticket: The ServiceNow ticket object.
        dry_run:
            True : Planned tool calls returned by the LLM will NOT be attempted
            False : Planned tool calls returned by the LLM WILL be attempted
    """

    config = load_config()
    service_now: ServiceNow = ServiceNow(config.servicenow_token)
    llm: LLM = LLM(config)

    full_ticket: FullTicket = service_now.get_full_ticket(ticket)

    # See note above about how the construct_prompt accesses config
    system_prompt, user_prompt = construct_prompt(full_ticket, config)

    # Here `response` = the text generated for the user to read (arguably the whole thing is a "response")
    # If there is a better terminology to distinguish this, then we should adopt that.
    llm_response: LLMResponse = llm.generate(system_prompt, user_prompt, config.llm_model)

    if not dry_run and llm_response.planned_tool_call is not None:
        call_tool(llm_response.planned_tool_call)

    _display_output(llm_response)


def batch_process_tickets(dry_run: bool):
    """
    Processes all of the available ServiceNow tickets, reviewing each one individually via an LLM.
    * The response and reasoning at displayed to the user.
    * If the LLM recommends one or more actions AND `dry_run` == false, the actions are
      performed.

    Params:
        dry_run:
            True : Planned tool calls returned by the LLM will NOT be attempted
            False : Planned tool calls returned by the LLM WILL be attempted
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
    service_now: ServiceNow = ServiceNow(config.servicenow_token)

    tickets: list[Ticket] = service_now.get_unassigned_tickets()
    for next_ticket in tickets:
        process_specific_ticket(next_ticket, dry_run)

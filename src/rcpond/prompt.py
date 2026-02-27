"""Prompt construction for rcpond, including reading RULES.md and formatting ticket data."""

from rcpond.config import Config
from rcpond.servicenow import FullTicket


def construct_prompt(full_ticket: FullTicket, config: Config) -> tuple[str, str]:  # noqa: ARG001
    """Construct the system and user prompts for the LLM given a full ticket and config.

    Reads the RULES.md file to form the system prompt. Formats the ticket data
    into the user prompt.

    Parameters
    ----------
    full_ticket : FullTicket
        The full ServiceNow ticket to construct the prompt for.
    config : Config
        The loaded configuration.

    Returns
    -------
    tuple[str, str]
        A (system_prompt, user_prompt) tuple.
    """
    # Read RULES.md to form the system prompt
    # Format full_ticket fields into the user prompt

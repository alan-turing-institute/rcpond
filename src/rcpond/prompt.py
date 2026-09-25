"""Prompt construction for rcpond, including reading RULES.md and formatting ticket data.

Provides a single public function:

- `construct_prompt`: Builds the (system_prompt, user_prompt) pair for the LLM given a full ticket and config.

The system prompt is formed by reading the rules file and rendering it into a template using Python's ``str.format``. The user prompt is the full ticket serialised as JSON.
"""

import dataclasses
import json

from rcpond.config import Config
from rcpond.servicenow import Ticket

## --------------------------------------------------------------------------------
## Interface to this module


def construct_prompt(full_ticket: Ticket, config: Config) -> tuple[str, str]:
    """Construct the system and user prompts for the LLM given a full ticket and config.

    Reads the rules file and renders it into the system prompt template. Serialises
    the full ticket as JSON for the user prompt.

    Parameters
    ----------
    full_ticket : Ticket
        The full ServiceNow ticket to construct the prompt for.
    config : Config
        The loaded configuration. ``config.rules_path`` and
        ``config.system_prompt_template_path`` must point to existing files —
        guaranteed by ``Config.__post_init__`` unless the config was built with
        ``require_rules_and_templates=False``, which no caller of this function does.

    Returns
    -------
    tuple[str, str]
        A (system_prompt, user_prompt) tuple.
    """
    assert config.rules_path is not None
    assert config.system_prompt_template_path is not None
    rules_text = config.rules_path.read_text()
    template_text = config.system_prompt_template_path.read_text()
    system_prompt = template_text.format(rules=rules_text)
    user_prompt = json.dumps(dataclasses.asdict(full_ticket), indent=2)
    return system_prompt.strip(), user_prompt.strip()

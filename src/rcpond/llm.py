"""An interface to an OpenAI-compatible chat completions API.

Provides a class, `LLM`, which wraps the chat completions endpoint.
The only function is:

- `LLM.generate()`: To generate a response given a system prompt and
  a user prompt, optionally with tool definitions.

Responses are returned as instances of an `LLMResponse` dataclass
containing the response text, optional reasoning content, and any
planned tool call.

The chat completions URL and API key are supplied via a `Config`
object.
"""

import json
from dataclasses import dataclass
from typing import Any

import requests

from rcpond.config import Config


@dataclass
class LLMResponse:
    """The parsed response from an LLM chat completion."""

    response_text: str
    """The text content of the response."""
    reasoning: str | None = None
    """Optional reasoning content (e.g. from models that support chain-of-thought)."""
    planned_tool_call: dict | None = None
    """Optional tool call requested by the model, with arguments parsed from JSON."""


## --------------------------------------------------------------------------------
## Interface to this module


class LLM:
    """Simple wrapper around an OpenAI-compatible chat completions API.

    Example:
    >>> llm = LLM(config)
    >>> response = llm.generate("You are helpful.", "Hello!", model="gpt-4")

    """

    def __init__(self, config: Config) -> None:
        """Initialise the LLM class.

        Parameters
        ----------
        config : Config
            Configuration object containing the chat completions URL and API key.
        """
        self.llm_chat_completions_url = config.llm_chat_completions_url
        self.llm_api_key = config.llm_api_key

    def _generate(self, messages: list[dict], model: str, tools: list[dict] | None = None) -> dict[str, Any]:
        """Generate a response from the LLM given a list of messages.

        Parameters
        ----------
        messages : list[dict]
            The messages to generate a response for, in OpenAI format.
        model : str
            The model to use for generation.
        tools : list[dict] | None
            Optional list of tool definitions in OpenAI format.

        Returns
        -------
        dict[str, Any]
            The generated response from the LLM as a parsed dictionary.
        """
        payload = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        response = requests.post(
            self.llm_chat_completions_url,
            headers={"Authorization": f"Bearer {self.llm_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def _parse_response(self, response: dict) -> LLMResponse:
        """Parse the response from the LLM into the `LLMResponse` dataclass.

        Parameters
        ----------
        response : dict
            The response from the LLM to parse.

        Returns
        -------
        LLMResponse
            The parsed response from the LLM.
        """
        message = response["choices"][0]["message"]
        response_text = message.get("content", "")
        reasoning = message.get("reasoning_content")
        tool_calls = message.get("tool_calls")
        planned_tool_call = None
        if tool_calls:
            ## The API returns function arguments as a JSON string;
            ## parse them into a dict for downstream use.
            tool_call = tool_calls[0]
            planned_tool_call = {
                **tool_call,
                "function": {
                    **tool_call["function"],
                    "arguments": json.loads(tool_call["function"]["arguments"]),
                },
            }
        return LLMResponse(
            response_text=response_text,
            reasoning=reasoning,
            planned_tool_call=planned_tool_call,
        )

    def generate(
        self, system_prompt: str, user_prompt: str, model: str, tools: list[dict] | None = None
    ) -> LLMResponse:
        """Generate an LLM response given a system prompt and a user prompt.
        Formats the system and user prompt into a single prompt and calls the `_generate` method to get the response from the LLM.
        LLM response is parsed into `LLMResponse` dataclass.

        Parameters
        ----------
        system_prompt : str
            The system prompt to provide context for the LLM.
        user_prompt : str
            The user prompt to generate a response for.
        model: str
            The model to use for generation.
        tools : list[dict] | None
            Optional list of tool definitions in OpenAI format.

        Returns
        -------
        LLMResponse
            The generated response from the LLM.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self._generate(messages, model=model, tools=tools)
        return self._parse_response(response)

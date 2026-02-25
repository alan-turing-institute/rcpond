from dataclasses import dataclass


@dataclass
class LLMResponse:
    response_text: str
    reasoning: str | None = None
    planned_tool_call: dict | None = None


class LLM:
    def __init__(self, base_url: str | None, api_key: str | None) -> None:
        """Initialise the LLM class.

        Parameters
        ----------
        base_url : str | None
            The base URL of the OpenAI compatible API. If None, will load from environment variable `OPENAI_BASE_URL`.
        api_key : str | None
            The API key for the OpenAI compatible API. If None, will load from environment variable `OPENAI_API_KEY`.
        """

    def _generate(self, prompt: str, model: str) -> str:
        """Generate a response from the LLM given a prompt.

        Parameters
        ----------
        prompt : str
            The prompt to generate a response for.
        model : str
            The model to use for generation.

        Returns
        -------
        dict
            The generated response from the LLM as json.
        """
        # Call requests.post to the OpenAI compatible API to get the response from the LLM
        # response = requests.post(
        #     f"{self.base_url}/v1/completions",
        #     headers={"Authorization": f"Bearer {self.api_key}"},
        #     json={
        #         "model": model,
        #         "prompt": prompt,
        #     }
        # )
        # response.raise_for_status()
        # return response.json()

    def _parse_response(self, response: str):
        """Parse the response from the LLM into the `LLMResponse` dataclass.

        Parameters
        ----------
        response : str
            The response from the LLM to parse.

        Returns
        -------
        LLMResponse
            The parsed response from the LLM.
        """
        # Example response
        # {"id":"95e9a85b25094094ace2ad03d2511637","model":"gpt-oss-120b","choices":[{"index":0,"message":{"role":"assistant","content":"Hello! How can I assist you today?","reasoning_content":"The user just says \"Hello\". Probably a greeting. We respond politely."},"finish_reason":"stop","content_filter_results":{"violence":{"filtered":false,"severity":"safe"},"sexual":{"filtered":false,"severity":"safe"},"hate":{"filtered":false,"severity":"safe"},"self_harm":{"filtered":false,"severity":"safe"}}}],"usage":{"prompt_tokens":68,"completion_tokens":34,"total_tokens":102,"audio_prompt_tokens":0},"created":1772030968,"object":"chat.completion","prompt_filter_results":[{"prompt_index":0,"content_filter_results":{"violence":{"filtered":false,"severity":"safe"},"sexual":{"filtered":false,"severity":"safe"},"hate":{"filtered":false,"severity":"safe"},"self_harm":{"filtered":false,"severity":"safe"},"jailbreak":{"filtered":false,"detected":false}}}]}%

        # Parse the response from the LLM into the `LLMResponse` dataclass
        # Also parse tool calls if they exist in response

    def generate(self, system_prompt: str, user_prompt: str, model: str) -> LLMResponse:
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

        Returns
        -------
        LLMResponse
            The generated response from the LLM.
        """

        # Format the system and user prompt into a single prompt
        # Call the `_generate` method to get the response from the LLM
        # `response = self._generate(prompt, model=model)`
        # Parse the response from the LLM into the `LLMResponse` dataclass
        # `llm_response = self._parse_response(response)`
        # return llm_response

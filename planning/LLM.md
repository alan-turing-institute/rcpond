# LLM Planning Notes

## Overview

The `LLM` class ([src/rcpond/llm.py](../src/rcpond/llm.py)) wraps an OpenAI-compatible API and exposes a simple `generate` interface that returns a structured `LLMResponse`.

## Design Decisions

### `__init__`
- Accepts `base_url` and `api_key`, falling back to environment variables `OPENAI_BASE_URL` and `OPENAI_API_KEY` if `None`.

### `_generate`
- Makes a POST request to `{base_url}/v1/chat/completions` using `requests` (not the openai SDK).
- Accepts a `messages` list in OpenAI format and a `model` string.
- Returns the raw response dict.

### `_parse_response`
- Parses the OpenAI-compatible JSON response into an `LLMResponse`.
- Fields to extract:
  - `response_text`: `choices[0].message.content`
  - `reasoning`: `choices[0].message.reasoning_content` (if present)
  - `planned_tool_call`: tool call info from `choices[0].message.tool_calls` (if present)
- Should handle missing optional fields gracefully.

### `generate`
- Accepts `system_prompt`, `user_prompt`, and `model` as parameters.
- Formats them internally into an OpenAI messages list:
  ```json
  [
    {"role": "system", "content": "<system_prompt>"},
    {"role": "user", "content": "<user_prompt>"}
  ]
  ```
- Calls `_generate(messages, model)`, then `_parse_response`, and returns the `LLMResponse`.

## Notes and Assumptions

- `planned_tool_call` in `LLMResponse` is a `dict | None` — the exact schema (single tool call vs list) is TBD.
- Tool definitions/schemas are not currently passed to `_generate`; this will be needed when tool-calling is wired up.
- Error handling (network errors, non-200 responses, malformed JSON) is not yet specified.

## TODOs

- **Extra model parameters**: Decide how to pass additional parameters to the model (e.g. `temperature`, `max_tokens`, `top_p`). Options:
  - Accept `**kwargs` in `generate`/`_generate` and forward them into the request body.
  - Accept an explicit `model_params: dict | None = None` argument.
  - Store defaults in `__init__` and allow per-call overrides.

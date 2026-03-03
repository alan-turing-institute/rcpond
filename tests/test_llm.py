from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from rcpond.config import Config
from rcpond.llm import LLM, LLMResponse

# Realistic mock responses based on actual API output from gpt-oss-120b

CHAT_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": "Hello! Hope you're having a wonderful day.",
                "reasoning_content": "The user asks to say hello in one sentence. Simple.",
            }
        }
    ]
}

TOOL_CALL_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": "",
                "reasoning_content": "The user asks for weather in London. Need to call get_weather.",
                "tool_calls": [
                    {
                        "id": "call_a69df960284a4438a6c2a203",
                        "index": 0,
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "London"}',
                        },
                    }
                ],
            }
        }
    ]
}

NO_REASONING_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": "Hello there!",
            }
        }
    ]
}


def make_config(**overrides):
    defaults = {
        "llm_chat_completions_url": "https://example.com/chat/completions",
        "llm_api_key": "test-key",
        "llm_model": "gpt-oss-120b",
        "servicenow_token": "fake-token",
        "servicenow_url": "https://example.com/servicenow",
        "rules_path": Path("/tmp/rules.txt"),
        "system_prompt_template_path": Path("/tmp/prompt.txt"),
    }
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture()
def llm():
    return LLM(make_config())


class TestInit:
    def test_init_stores_values(self):
        config = make_config(llm_chat_completions_url="https://example.com/chat", llm_api_key="my-key")
        llm = LLM(config)
        assert llm.llm_chat_completions_url == "https://example.com/chat"
        assert llm.llm_api_key == "my-key"


class TestGenerate:
    @patch("rcpond.llm.requests.post")
    def test_generate_sends_correct_payload(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = CHAT_RESPONSE
        mock_post.return_value = mock_response

        llm._generate(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-oss-120b",
        )

        mock_post.assert_called_once_with(
            "https://example.com/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "Hi"}]},
        )

    @patch("rcpond.llm.requests.post")
    def test_generate_includes_tools_when_provided(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = TOOL_CALL_RESPONSE
        mock_post.return_value = mock_response

        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        llm._generate(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-oss-120b",
            tools=tools,
        )

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["tools"] == tools

    # e.g. cannot connect
    @patch("rcpond.llm.requests.post")
    def test_generate_raises_on_connection_error(self, mock_post, llm):
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect")

        with pytest.raises(requests.exceptions.ConnectionError):
            llm._generate(messages=[{"role": "user", "content": "Hi"}], model="gpt-oss-120b")

    # e.g. invalid model chosen
    @patch("rcpond.llm.requests.post")
    def test_generate_raises_on_http_error(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        with pytest.raises(requests.exceptions.HTTPError):
            llm._generate(messages=[{"role": "user", "content": "Hi"}], model="fake-model")

    @patch("rcpond.llm.requests.post")
    def test_generate_does_not_include_tools_when_none(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = CHAT_RESPONSE
        mock_post.return_value = mock_response

        llm._generate(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-oss-120b",
        )

        call_kwargs = mock_post.call_args
        assert "tools" not in call_kwargs.kwargs["json"]


class TestParseResponse:
    def test_parse_chat_response(self, llm):
        result = llm._parse_response(CHAT_RESPONSE)

        assert isinstance(result, LLMResponse)
        assert result.response_text == "Hello! Hope you're having a wonderful day."
        assert result.reasoning == "The user asks to say hello in one sentence. Simple."
        assert result.planned_tool_call is None

    def test_parse_tool_call_response(self, llm):
        # Verify the raw API response has arguments as a JSON string
        raw_arguments = TOOL_CALL_RESPONSE["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(raw_arguments, str)

        result = llm._parse_response(TOOL_CALL_RESPONSE)

        assert result.response_text == ""
        assert result.planned_tool_call is not None
        assert result.planned_tool_call["function"]["name"] == "get_weather"
        # _parse_response should convert arguments from JSON string to dict
        assert isinstance(result.planned_tool_call["function"]["arguments"], dict)
        assert result.planned_tool_call["function"]["arguments"] == {"location": "London"}

    def test_parse_response_without_reasoning(self, llm):
        result = llm._parse_response(NO_REASONING_RESPONSE)

        assert result.response_text == "Hello there!"
        assert result.reasoning is None
        assert result.planned_tool_call is None


class TestGenerateEndToEnd:
    @patch("rcpond.llm.requests.post")
    def test_generate_end_to_end_chat(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = CHAT_RESPONSE
        mock_post.return_value = mock_response

        result = llm.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="Say hello in one sentence.",
            model="gpt-oss-120b",
        )

        assert isinstance(result, LLMResponse)
        assert result.response_text == "Hello! Hope you're having a wonderful day."

        # Verify messages were formatted correctly
        call_kwargs = mock_post.call_args
        messages = call_kwargs.kwargs["json"]["messages"]
        assert messages[0] == {"role": "system", "content": "You are a helpful assistant."}
        assert messages[1] == {"role": "user", "content": "Say hello in one sentence."}

    @patch("rcpond.llm.requests.post")
    def test_generate_end_to_end_tool_call(self, mock_post, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = TOOL_CALL_RESPONSE
        mock_post.return_value = mock_response

        tools = [{"type": "function", "function": {"name": "get_weather"}}]
        result = llm.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the weather in London?",
            model="gpt-oss-120b",
            tools=tools,
        )

        assert result.planned_tool_call["function"]["arguments"] == {"location": "London"}

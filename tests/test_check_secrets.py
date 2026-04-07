import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pre-commit-scripts"))

from check_secrets import check_file, main

# --- Helpers ---


def write_file(tmp_path, content: str) -> str:
    p = tmp_path / "test.env"
    p.write_text(content)
    return str(p)


# --- Separator formats ---


@pytest.mark.parametrize(
    "line",
    [
        "RCPOND_LLM_API_KEY=real-secret",
        "RCPOND_LLM_API_KEY: real-secret",
        "RCPOND_LLM_API_KEY real-secret",
        "RCPOND_LLM_API_KEY = real-secret",
    ],
)
def test_real_secret_detected_for_all_separator_styles(tmp_path, line):
    path = write_file(tmp_path, line + "\n")
    assert check_file(path) != []


# --- Commented-out lines are still caught ---


@pytest.mark.parametrize(
    "line",
    [
        "# RCPOND_LLM_API_KEY=real-secret",
        "# RCPOND_SERVICENOW_TOKEN=real-secret",
    ],
)
def test_commented_out_secret_is_flagged(tmp_path, line):
    path = write_file(tmp_path, line + "\n")
    assert check_file(path) != []


# --- Safe placeholder values ---


@pytest.mark.parametrize(
    "line",
    [
        "RCPOND_LLM_API_KEY=your-api-key-here",
        "RCPOND_SERVICENOW_TOKEN=your-servicenow-token",
        "RCPOND_SERVICENOW_CLIENT_ID=your-client-id",
        "RCPOND_SERVICENOW_CLIENT_SECRET=your-client-secret",
        "RCPOND_LLM_API_KEY=",
    ],
)
def test_safe_placeholder_not_flagged(tmp_path, line):
    path = write_file(tmp_path, line + "\n")
    assert check_file(path) == []


# --- All secret keys are checked ---


@pytest.mark.parametrize(
    "line",
    [
        "RCPOND_LLM_API_KEY=real-secret",
        "RCPOND_SERVICENOW_TOKEN=real-secret",
        "RCPOND_SERVICENOW_CLIENT_ID=abc123realid",
        "RCPOND_SERVICENOW_CLIENT_SECRET=abc123realsecret",
    ],
)
def test_each_secret_key_is_flagged(tmp_path, line):
    path = write_file(tmp_path, line + "\n")
    assert check_file(path) != []


# --- Non-matching lines ignored ---


def test_unrelated_key_ignored(tmp_path):
    path = write_file(tmp_path, "SOME_OTHER_KEY=real-secret\n")
    assert check_file(path) == []


# --- main() exit codes ---


def test_main_returns_1_on_violation(tmp_path):
    path = write_file(tmp_path, "RCPOND_LLM_API_KEY=real-secret\n")
    assert main([path]) == 1


def test_main_returns_0_when_clean(tmp_path):
    path = write_file(tmp_path, "RCPOND_LLM_API_KEY=your-api-key-here\n")
    assert main([path]) == 0


# --- env.example passes cleanly ---


def test_env_example_is_clean():
    env_example = Path(__file__).parent / "env.example"
    assert check_file(str(env_example)) == []

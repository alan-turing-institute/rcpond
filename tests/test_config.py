from dataclasses import fields

import pytest

from rcpond.config import Config

# --- Fixtures ---


@pytest.fixture()
def path_files(tmp_path):
    """Create placeholder files for the two Path config fields."""
    rules = tmp_path / "RULES.md"
    rules.touch()
    template = tmp_path / "system_prompt_template.txt"
    template.touch()
    return rules, template


@pytest.fixture()
def all_values(path_files):
    """A complete set of config values with valid paths."""
    rules, template = path_files
    return {
        "llm_chat_completions_url": "https://api.example.com",
        "llm_api_key": "test-api-key",
        "llm_model": "gpt-4",
        "servicenow_token": "sn-token",
        "servicenow_url": "https://snow.example.com",
        "rules_path": str(rules),
        "system_prompt_template_path": str(template),
    }


def write_dotenv(directory, values):
    """Write a .env file with RCPOND_-prefixed keys to a directory."""
    env_file = directory / ".env"
    lines = [f"RCPOND_{k.upper()}={v}" for k, v in values.items()]
    env_file.write_text("\n".join(lines))
    return env_file


# --- Loading from a single source ---


def test_load_from_dotenv_only(tmp_path, all_values, path_files):
    rules, template = path_files
    env_file = write_dotenv(tmp_path, all_values)

    config = Config(env_path=env_file)

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_api_key == "test-api-key"
    assert config.llm_model == "gpt-4"
    assert config.rules_path == rules.resolve()
    assert config.system_prompt_template_path == template.resolve()


def test_load_from_env_vars_only(monkeypatch, all_values):
    for key, value in all_values.items():
        monkeypatch.setenv(f"RCPOND_{key.upper()}", value)

    config = Config()

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_model == "gpt-4"


def test_load_from_cli_args_only(all_values):
    config = Config(cli_args=all_values)

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_model == "gpt-4"


# --- Precedence ---


def test_env_vars_override_dotenv(tmp_path, monkeypatch, all_values):
    env_file = write_dotenv(tmp_path, all_values)
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config(env_path=env_file)

    assert config.llm_model != all_values["llm_model"]
    assert config.llm_model == "env-var-model"


def test_cli_args_override_env_vars(monkeypatch, all_values):
    for key, value in all_values.items():
        monkeypatch.setenv(f"RCPOND_{key.upper()}", value)

    cli_args = dict(all_values)
    cli_args["llm_model"] = "cli-model"
    config = Config(cli_args=cli_args)

    assert config.llm_model != all_values["llm_model"]
    assert config.llm_model == "cli-model"


def test_cli_args_override_dotenv(tmp_path, all_values):
    env_file = write_dotenv(tmp_path, all_values)

    config = Config(env_path=env_file, cli_args={"llm_model": "cli-model"})

    assert config.llm_model != all_values["llm_model"]
    assert config.llm_model == "cli-model"


def test_all_three_sources_cli_args_wins(tmp_path, monkeypatch, all_values):
    env_file = write_dotenv(tmp_path, all_values)
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config(env_path=env_file, cli_args={"llm_model": "cli-model"})

    assert config.llm_model != all_values["llm_model"]
    assert config.llm_model != "env-var-model"
    assert config.llm_model == "cli-model"


# --- None handling ---


def test_cli_args_none_does_not_override_dotenv(tmp_path, all_values):
    """A None value in cli_args should be ignored, not used to override."""
    env_file = write_dotenv(tmp_path, all_values)

    config = Config(env_path=env_file, cli_args={"llm_model": None})

    assert config.llm_model == "gpt-4"


def test_both_params_none_raises_when_no_env_vars_set(monkeypatch):
    """With no sources at all, Config() should raise."""
    from rcpond.config import _env_var_name

    for field in fields(Config):
        monkeypatch.delenv(_env_var_name(field.name), raising=False)

    with pytest.raises(ValueError, match="Missing required configuration"):
        Config(env_path=None, cli_args=None)


# --- Missing fields ---


def test_missing_single_field_raises(tmp_path, all_values):
    partial = {k: v for k, v in all_values.items() if k != "llm_api_key"}
    env_file = write_dotenv(tmp_path, partial)

    with pytest.raises(ValueError, match="llm_api_key"):
        Config(env_path=env_file)


def test_missing_multiple_fields_raises(tmp_path, all_values):
    partial = {k: v for k, v in all_values.items() if k in ("llm_base_url", "llm_model")}
    env_file = write_dotenv(tmp_path, partial)

    with pytest.raises(ValueError, match="Missing required configuration"):
        Config(env_path=env_file)


# --- Invalid paths ---


def test_invalid_rules_path_raises(all_values):
    invalid_values = dict(all_values)
    invalid_values["rules_path"] = "/nonexistent/RULES.md"

    with pytest.raises(ValueError, match="/nonexistent/RULES.md"):
        Config(cli_args=invalid_values)


def test_invalid_template_path_raises(all_values):
    invalid_values = dict(all_values)
    invalid_values["system_prompt_template_path"] = "/nonexistent/template.txt"

    with pytest.raises(ValueError, match="/nonexistent/template.txt"):
        Config(cli_args=invalid_values)


# --- dotenv format ---


def test_dotenv_malformed_line_raises(tmp_path, all_values):
    env_file = tmp_path / ".env"
    lines = ["# comment", ""]
    lines += [f"RCPOND_{k.upper()}={v}" for k, v in all_values.items()]
    lines.insert(4, "RCPOND_LLM_MODEL gpt-4")  # line 3 (after comment + blank): missing '='
    env_file.write_text("\n".join(lines))

    with pytest.raises(ValueError, match="line 5"):
        Config(env_path=env_file)


def test_dotenv_duplicate_key_raises(tmp_path, all_values):
    env_file = tmp_path / ".env"
    lines = [f"RCPOND_{k.upper()}={v}" for k, v in all_values.items()]
    lines.append("RCPOND_LLM_MODEL=gpt-3.5")  # duplicate of an earlier line
    env_file.write_text("\n".join(lines))

    with pytest.raises(ValueError, match="RCPOND_LLM_MODEL"):
        Config(env_path=env_file)


def test_dotenv_ignores_comments_and_blank_lines(tmp_path, all_values):
    env_file = tmp_path / ".env"
    lines = ["# This is a comment", ""]
    lines += [f"RCPOND_{k.upper()}={v}" for k, v in all_values.items()]
    env_file.write_text("\n".join(lines))

    config = Config(env_path=env_file)

    assert config.llm_model == "gpt-4"


# --- Dataclass structure ---


def test_fields_are_config_values_only():
    """InitVar params (env_path, cli_args) must not appear in fields()."""
    field_names = [f.name for f in fields(Config)]
    assert field_names == [
        "llm_chat_completions_url",
        "llm_api_key",
        "llm_model",
        "servicenow_token",
        "servicenow_url",
        "rules_path",
        "system_prompt_template_path",
    ]

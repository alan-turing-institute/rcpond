"""Tests for Config loading, precedence, and validation.

XDG isolation
-------------
``XDG_CONFIG_HOME`` is redirected to a per-test ``tmp_path`` by the ``isolated_xdg_config``
autouse fixture, so the developer's own ``~/.config/rcpond/default.config`` never leaks
into the test suite.
"""

from dataclasses import fields
from pathlib import Path

import pytest

from rcpond.config import Config

_WORKING_TEMPLATES_DIR = Path("tests/fixtures/working_templates")
_FAILING_TEMPLATES_DIR = Path("tests/fixtures/failing_templates")
_SYSTEM_PROMPT_TEMPLATE = Path("tests/fixtures/system_prompt_template.txt")

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _isolated_xdg_config(tmp_path, monkeypatch):
    """Redirect XDG_CONFIG_HOME to a tmp dir for every test.

    Prevents the developer's own ~/.config/rcpond/default.config from leaking
    into tests that assert on missing or specific config values.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture()
def path_files(tmp_path):
    """Create placeholder files/dirs for the three Path config fields."""
    rules = tmp_path / "RULES.md"
    rules.touch()
    sys_prompt_template = tmp_path / "system_prompt_template.txt"
    sys_prompt_template.write_text(_SYSTEM_PROMPT_TEMPLATE.read_text())
    email_templates = _WORKING_TEMPLATES_DIR
    return rules, sys_prompt_template, email_templates


@pytest.fixture()
def common_config_values(path_files):
    """A complete set of config values with valid paths."""
    rules, sys_prompt_template, email_templates = path_files
    return {
        "llm_chat_completions_url": "https://api.example.com",
        "llm_api_key": "test-api-key",
        "llm_model": "gpt-4",
        "servicenow_token": "sn-token",
        "servicenow_url": "https://snow.example.com",
        "servicenow_web_url": "https://alanturingdev.service-now.com",
        "servicenow_oauth_scope": "useraccount",
        "servicenow_oauth_redirect_port": "8765",
        "servicenow_oauth_auth_url": "https://alanturingdev.service-now.com/oauth_auth.do",
        "servicenow_oauth_token_url": "https://alanturingdev.service-now.com/oauth_token.do",
        "rules_path": str(rules),
        "system_prompt_template_path": str(sys_prompt_template),
        "email_templates_dir": str(email_templates),
    }


def write_dotenv(directory, values):
    """Write a .env file with RCPOND_-prefixed keys to a directory."""
    env_file = directory / ".env"
    lines = [f"RCPOND_{k.upper()}={v}" for k, v in values.items()]
    env_file.write_text("\n".join(lines))
    return env_file


def write_xdg_config(xdg_dir, values):
    """Write a config file at $XDG_CONFIG_HOME/rcpond/default.config."""
    config_dir = xdg_dir / "rcpond"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "default.config"
    lines = [f"RCPOND_{k.upper()}={v}" for k, v in values.items()]
    config_file.write_text("\n".join(lines))
    return config_file


# --- Loading from a single source ---


def test_load_from_dotenv_only(tmp_path, common_config_values, path_files):
    rules, sys_prompt_template, email_templates = path_files
    env_file = write_dotenv(tmp_path, common_config_values)

    config = Config(env_path=env_file)

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_api_key == "test-api-key"
    assert config.llm_model == "gpt-4"
    assert config.rules_path == rules.resolve()
    assert config.system_prompt_template_path == sys_prompt_template.resolve()
    assert config.email_templates_dir == email_templates.resolve()


def test_load_from_env_vars_only(monkeypatch, common_config_values):
    for key, value in common_config_values.items():
        monkeypatch.setenv(f"RCPOND_{key.upper()}", value)

    config = Config()

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_model == "gpt-4"


def test_load_from_cli_args_only(common_config_values):
    config = Config(cli_args=common_config_values)

    assert config.llm_chat_completions_url == "https://api.example.com"
    assert config.llm_model == "gpt-4"


# --- Precedence ---


def test_env_vars_override_dotenv(tmp_path, monkeypatch, common_config_values):
    env_file = write_dotenv(tmp_path, common_config_values)
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config(env_path=env_file)

    assert config.llm_model != common_config_values["llm_model"]
    assert config.llm_model == "env-var-model"


def test_cli_args_override_env_vars(monkeypatch, common_config_values):
    for key, value in common_config_values.items():
        monkeypatch.setenv(f"RCPOND_{key.upper()}", value)

    cli_args = dict(common_config_values)
    cli_args["llm_model"] = "cli-model"
    config = Config(cli_args=cli_args)

    assert config.llm_model != common_config_values["llm_model"]
    assert config.llm_model == "cli-model"


def test_cli_args_override_dotenv(tmp_path, common_config_values):
    env_file = write_dotenv(tmp_path, common_config_values)

    config = Config(env_path=env_file, cli_args={"llm_model": "cli-model"})

    assert config.llm_model != common_config_values["llm_model"]
    assert config.llm_model == "cli-model"


def test_all_three_sources_cli_args_wins(tmp_path, monkeypatch, common_config_values):
    env_file = write_dotenv(tmp_path, common_config_values)
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config(env_path=env_file, cli_args={"llm_model": "cli-model"})

    assert config.llm_model != common_config_values["llm_model"]
    assert config.llm_model != "env-var-model"
    assert config.llm_model == "cli-model"


# --- None handling ---


def test_cli_args_none_does_not_override_dotenv(tmp_path, common_config_values):
    """A None value in cli_args should be ignored, not used to override."""
    env_file = write_dotenv(tmp_path, common_config_values)

    config = Config(env_path=env_file, cli_args={"llm_model": None})

    assert config.llm_model == "gpt-4"


def test_both_params_none_raises_when_no_env_vars_set(monkeypatch):
    """With no sources at all, Config() should raise."""
    from rcpond.config import _env_var_name

    for field in fields(Config):
        monkeypatch.delenv(_env_var_name(field.name), raising=False)

    with pytest.raises(ValueError, match="Missing required configuration"):
        Config(env_path=None, cli_args=None)


# --- XDG config loading ---


def test_load_from_xdg_config_only(tmp_path, common_config_values):
    """Config loads from the XDG default.config file when present."""
    write_xdg_config(tmp_path, common_config_values)

    config = Config()

    assert config.llm_model == "gpt-4"
    assert config.llm_chat_completions_url == "https://api.example.com"


def test_xdg_config_absent_does_not_raise(tmp_path, common_config_values):
    """Missing XDG config is silently ignored; other sources still work."""
    env_file = write_dotenv(tmp_path, common_config_values)

    config = Config(env_path=env_file)

    assert config.llm_model == "gpt-4"


def test_dotenv_overrides_xdg_config(tmp_path, common_config_values):
    write_xdg_config(tmp_path, common_config_values)
    env_file = write_dotenv(tmp_path, {**common_config_values, "llm_model": "dotenv-model"})

    config = Config(env_path=env_file)

    assert config.llm_model == "dotenv-model"


def test_env_file_replaces_xdg_config_entirely(tmp_path, common_config_values):
    """When --env-file is given, the XDG default.config is ignored entirely.

    A field present only in XDG (not in env_file) must raise a missing-field
    error, even though it could have been satisfied by the XDG file.
    """
    write_xdg_config(tmp_path, common_config_values)
    ## env_file is deliberately missing llm_api_key
    partial = {k: v for k, v in common_config_values.items() if k != "llm_api_key"}
    env_file = write_dotenv(tmp_path, partial)

    with pytest.raises(ValueError, match="llm_api_key"):
        Config(env_path=env_file)


def test_env_vars_override_xdg_config(tmp_path, monkeypatch, common_config_values):
    write_xdg_config(tmp_path, common_config_values)
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config()

    assert config.llm_model == "env-var-model"


def test_cli_args_override_xdg_config(tmp_path, common_config_values):
    write_xdg_config(tmp_path, common_config_values)

    config = Config(cli_args={"llm_model": "cli-model"})

    assert config.llm_model == "cli-model"


def test_all_four_sources_precedence(tmp_path, monkeypatch, common_config_values):
    """Full precedence chain: xdg < dotenv < env vars < cli args."""
    write_xdg_config(tmp_path, common_config_values)
    env_file = write_dotenv(tmp_path, {**common_config_values, "llm_model": "dotenv-model"})
    monkeypatch.setenv("RCPOND_LLM_MODEL", "env-var-model")

    config = Config(env_path=env_file, cli_args={"llm_model": "cli-model"})

    assert config.llm_model == "cli-model"


# --- Missing fields ---


def test_missing_single_field_raises(tmp_path, common_config_values):
    partial = {k: v for k, v in common_config_values.items() if k != "llm_api_key"}
    env_file = write_dotenv(tmp_path, partial)

    with pytest.raises(ValueError, match="llm_api_key"):
        Config(env_path=env_file)


def test_missing_multiple_fields_raises(tmp_path, common_config_values):
    partial = {k: v for k, v in common_config_values.items() if k in ("llm_base_url", "llm_model")}
    env_file = write_dotenv(tmp_path, partial)

    with pytest.raises(ValueError, match="Missing required configuration"):
        Config(env_path=env_file)


# --- Invalid paths ---


def test_invalid_rules_path_raises(common_config_values):
    invalid_values = dict(common_config_values)
    invalid_values["rules_path"] = "/nonexistent/RULES.md"

    with pytest.raises(ValueError, match="/nonexistent/RULES.md"):
        Config(cli_args=invalid_values)


def test_invalid_template_path_raises(common_config_values):
    invalid_values = dict(common_config_values)
    invalid_values["system_prompt_template_path"] = "/nonexistent/template.txt"

    with pytest.raises(ValueError, match="/nonexistent/template.txt"):
        Config(cli_args=invalid_values)


def test_invalid_email_templates_dir_raises(common_config_values):
    invalid_values = dict(common_config_values)
    invalid_values["email_templates_dir"] = "/nonexistent/email_templates"

    with pytest.raises(ValueError, match="/nonexistent/email_templates"):
        Config(cli_args=invalid_values)


# --- Jinja2 template validation ---


def test_email_templates_dir_no_j2_files_raises(common_config_values, tmp_path):
    empty_dir = tmp_path / "empty_templates"
    empty_dir.mkdir()
    invalid = dict(common_config_values, email_templates_dir=str(empty_dir))
    with pytest.raises(ValueError, match=r"[Nn]o.*\.j2"):
        Config(cli_args=invalid)


def test_email_templates_dir_invalid_jinja_raises(common_config_values, tmp_path):
    malformed_content = next(_FAILING_TEMPLATES_DIR.glob("*.j2")).read_text()
    bad_dir = tmp_path / "bad_templates"
    bad_dir.mkdir()
    (bad_dir / "bad.yaml.j2").write_text(malformed_content)
    invalid = dict(common_config_values, email_templates_dir=str(bad_dir))
    with pytest.raises(ValueError, match="bad.yaml.j2"):
        Config(cli_args=invalid)


def test_email_templates_dir_multiple_invalid_jinja_lists_all(common_config_values, tmp_path):
    malformed_content = next(_FAILING_TEMPLATES_DIR.glob("*.j2")).read_text()
    bad_dir = tmp_path / "bad_templates"
    bad_dir.mkdir()
    (bad_dir / "bad_one.yaml.j2").write_text(malformed_content)
    (bad_dir / "bad_two.yaml.j2").write_text(malformed_content)
    invalid = dict(common_config_values, email_templates_dir=str(bad_dir))
    with pytest.raises(ValueError) as exc_info:  # noqa: PT011
        Config(cli_args=invalid)
    msg = str(exc_info.value)
    assert "bad_one.yaml.j2" in msg
    assert "bad_two.yaml.j2" in msg


def test_system_prompt_template_invalid_jinja_raises(common_config_values, tmp_path):
    malformed_content = next(_FAILING_TEMPLATES_DIR.glob("*.j2")).read_text()
    bad_template = tmp_path / "bad_template.txt"
    bad_template.write_text(malformed_content)
    invalid = dict(common_config_values, system_prompt_template_path=str(bad_template))
    with pytest.raises(ValueError, match="bad_template.txt"):
        Config(cli_args=invalid)


def test_email_templates_dir_valid_j2_passes(common_config_values):
    config = Config(cli_args=common_config_values)
    assert config.email_templates_dir.exists()


## ticket field validation — templates may reference ticket.<field>, but only
## fields that actually exist on FullTicket are permitted


def test_email_templates_dir_unknown_ticket_field_raises(common_config_values, tmp_path):
    ## A template referencing a non-existent ticket field should be rejected
    bad_dir = tmp_path / "bad_templates"
    bad_dir.mkdir()
    (bad_dir / "bad.yaml.j2").write_text("subject: {{ ticket.fake_field }}")
    invalid = dict(common_config_values, email_templates_dir=str(bad_dir))
    with pytest.raises(ValueError, match="fake_field"):
        Config(cli_args=invalid)


def test_email_templates_dir_unknown_ticket_field_lists_all(common_config_values, tmp_path):
    ## All bad field names across all templates should appear in the error message
    bad_dir = tmp_path / "bad_templates"
    bad_dir.mkdir()
    (bad_dir / "one.yaml.j2").write_text("subject: {{ ticket.bad_one }}")
    (bad_dir / "two.yaml.j2").write_text("subject: {{ ticket.bad_two }}")
    invalid = dict(common_config_values, email_templates_dir=str(bad_dir))
    with pytest.raises(ValueError) as exc_info:  # noqa: PT011
        Config(cli_args=invalid)
    msg = str(exc_info.value)
    assert "bad_one" in msg
    assert "bad_two" in msg


def test_email_templates_dir_valid_ticket_fields_pass(common_config_values, tmp_path):
    ## Templates using real FullTicket fields should pass validation
    good_dir = tmp_path / "good_templates"
    good_dir.mkdir()
    (good_dir / "good.yaml.j2").write_text("subject: {{ ticket.number }} - {{ ticket.project_title }}")
    valid = dict(common_config_values, email_templates_dir=str(good_dir))
    config = Config(cli_args=valid)
    assert config.email_templates_dir.exists()


# --- dotenv format ---


def test_dotenv_malformed_line_raises(tmp_path, common_config_values):
    env_file = tmp_path / ".env"
    lines = ["# comment", ""]
    lines += [f"RCPOND_{k.upper()}={v}" for k, v in common_config_values.items()]
    lines.insert(4, "RCPOND_LLM_MODEL gpt-4")  # line 3 (after comment + blank): missing '='
    env_file.write_text("\n".join(lines))

    with pytest.raises(ValueError, match="line 5"):
        Config(env_path=env_file)


def test_dotenv_duplicate_key_raises(tmp_path, common_config_values):
    env_file = tmp_path / ".env"
    lines = [f"RCPOND_{k.upper()}={v}" for k, v in common_config_values.items()]
    lines.append("RCPOND_LLM_MODEL=gpt-3.5")  # duplicate of an earlier line
    env_file.write_text("\n".join(lines))

    with pytest.raises(ValueError, match="RCPOND_LLM_MODEL"):
        Config(env_path=env_file)


def test_dotenv_ignores_comments_and_blank_lines(tmp_path, common_config_values):
    env_file = tmp_path / ".env"
    lines = ["# This is a comment", ""]
    lines += [f"RCPOND_{k.upper()}={v}" for k, v in common_config_values.items()]
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
        "servicenow_web_url",
        "servicenow_client_id",
        "servicenow_client_secret",
        "servicenow_oauth_scope",
        "servicenow_oauth_redirect_port",
        "servicenow_oauth_auth_url",
        "servicenow_oauth_token_url",
        "rules_path",
        "system_prompt_template_path",
        "email_templates_dir",
    ]


# --- OAuth / servicenow_token conditional requirement ---


def test_servicenow_token_required_without_oauth(tmp_path, common_config_values):
    ## servicenow_token must be supplied when no OAuth credentials are set
    servicenow_auth_keys = ["servicenow_token", "servicenow_client_id", "servicenow_client_secret"]
    partial = {k: v for k, v in common_config_values.items() if k not in servicenow_auth_keys}
    env_file = write_dotenv(tmp_path, partial)
    with pytest.raises(ValueError, match="servicenow_token"):
        Config(env_path=env_file)


def test_servicenow_token_optional_when_oauth_present(tmp_path, common_config_values):
    ## servicenow_token may be omitted when OAuth credentials are provided
    oauth_values = {k: v for k, v in common_config_values.items() if k != "servicenow_token"}
    oauth_values["servicenow_client_id"] = "my-client-id"
    oauth_values["servicenow_client_secret"] = "my-client-secret"
    env_file = write_dotenv(tmp_path, oauth_values)
    config = Config(env_path=env_file)
    assert config.servicenow_token is None
    assert config.servicenow_client_id == "my-client-id"
    assert config.servicenow_client_secret == "my-client-secret"


def test_oauth_fields_absent_when_not_configured(common_config_values):
    ## OAuth fields default to None when not supplied
    assert "servicenow_client_id" not in common_config_values
    assert "servicenow_client_secret" not in common_config_values
    config = Config(cli_args=common_config_values)
    assert config.servicenow_client_id is None
    assert config.servicenow_client_secret is None


def test_oauth_only_fields_optional_without_oauth_credentials(common_config_values):
    ## All four OAuth-only fields may be omitted when OAuth credentials are absent
    for key in (
        "servicenow_oauth_scope",
        "servicenow_oauth_redirect_port",
        "servicenow_oauth_auth_url",
        "servicenow_oauth_token_url",
    ):
        del common_config_values[key]
    config = Config(cli_args=common_config_values)
    assert config.servicenow_oauth_scope is None
    assert config.servicenow_oauth_redirect_port is None
    assert config.servicenow_oauth_auth_url is None
    assert config.servicenow_oauth_token_url is None


def test_oauth_scope_required_when_oauth_credentials_present(common_config_values):
    oauth_values = {**common_config_values, "servicenow_client_id": "cid", "servicenow_client_secret": "csec"}
    del oauth_values["servicenow_oauth_scope"]
    with pytest.raises(ValueError, match="servicenow_oauth_scope"):
        Config(cli_args=oauth_values)


def test_oauth_redirect_port_required_when_oauth_credentials_present(common_config_values):
    oauth_values = {**common_config_values, "servicenow_client_id": "cid", "servicenow_client_secret": "csec"}
    del oauth_values["servicenow_oauth_redirect_port"]
    with pytest.raises(ValueError, match="servicenow_oauth_redirect_port"):
        Config(cli_args=oauth_values)


def test_oauth_scope_and_port_configurable(common_config_values):
    config = Config(
        cli_args={
            **common_config_values,
            "servicenow_oauth_scope": "custom_scope",
            "servicenow_oauth_redirect_port": "9000",
        }
    )
    assert config.servicenow_oauth_scope == "custom_scope"
    assert config.servicenow_oauth_redirect_port == 9000


def test_oauth_wins_when_both_configured(common_config_values):
    ## When all three are set, both token and OAuth fields are present; servicenow.py decides which to use
    config = Config(
        cli_args={**common_config_values, "servicenow_client_id": "cid", "servicenow_client_secret": "csecret"}
    )
    assert config.servicenow_token is not None
    assert config.servicenow_client_id == "cid"
    assert config.servicenow_client_secret == "csecret"

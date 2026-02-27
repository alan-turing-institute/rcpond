"""Configuration loading and validation for rcpond."""

import os
import typing
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    """Validated runtime configuration for rcpond.

    Normally callers should not create this class directly, but use the function
    `load_config` instead. `load_config` will populated the fields from .env file,
    environment variables, and/or CLI arguments, ensureing that all fields are
    present and that path fields are resolved and checked for existence at load time.

    Attributes
    ----------
    llm_base_url : str
        Base URL of the LLM API endpoint.
    llm_api_key : str
        API key for authenticating with the LLM provider.
    llm_model : str
        Model identifier to use for LLM requests.
    servicenow_token : str
        Bearer token for authenticating with the ServiceNow API.
    servicenow_url : str
        Base URL of the ServiceNow instance.
    rules_path : Path
        Path to the RULES.md file used to construct the system prompt.
    system_prompt_template_path : Path
        Path to the Jinja2 template used to render the system prompt.
    """

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    servicenow_token: str
    servicenow_url: str
    rules_path: Path
    system_prompt_template_path: Path


def _env_var_name(field_name: str) -> str:
    return f"RCPOND_{field_name.upper()}"


def _parse_dotenv(env_path: Path) -> dict[str, str]:
    result = {}
    for line_number, raw_line in enumerate(env_path.read_text().splitlines(), start=1):
        line = raw_line.strip()

        # Skip over comments
        if not line or line.startswith("#"):
            continue

        # Error if a non-blank line is not a comment or a value assigned with a `=`
        if "=" not in line:
            msg = f"Malformed line {line_number} in {env_path}: {raw_line!r}"
            raise ValueError(msg)
        key, _, value = line.partition("=")
        key = key.strip()

        # Error if there are duplicate keys
        if key in result:
            msg = f"Duplicate key {key!r} at line {line_number} in {env_path}"
            raise ValueError(msg)

        # Now we have the actual value
        result[key] = value.strip()
    return result


def _confirm_path_exists(path_as_str: str) -> Path:
    path = Path(path_as_str).resolve()

    if path.exists():
        return path

    err_msg = f"Path {path_as_str} cannot be found"
    raise ValueError(err_msg)


def load_config(env_path: Path | None = None, cli_args: dict | None = None) -> Config:
    """Load configuration from .env file, environment variables, and CLI args.

    Precedence (lowest to highest):
    - .env file
    - environment variables
    - cli_args.

    Meaning that:
    - any values specified in environment variable will override those in a .env file.
    - any values specified in cli_args will override those in either a .env file or an
      environment variable.

    Raises ValueError if any required field is missing after all sources are merged.

    Parameters
    ----------
    env_path : Path | None
        Path to a .env file to load. If None, no .env file is read.
    cli_args : dict | None
        Dict of config field names to values from the CLI. None values are ignored.

    Returns
    -------
    Config
        The loaded and validated configuration.
    """
    values: dict[str, str] = {}

    # 1. Load from .env file (lowest precedence)
    if env_path is not None:
        dotenv_vars = _parse_dotenv(env_path)
        for field in fields(Config):
            env_key = _env_var_name(field.name)
            if env_key in dotenv_vars:
                values[field.name] = dotenv_vars[env_key]

    # 2. Override with actual environment variables
    for field in fields(Config):
        env_key = _env_var_name(field.name)
        if env_key in os.environ:
            values[field.name] = os.environ[env_key]

    # 3. Override with CLI args (highest precedence)
    if cli_args:
        for field in fields(Config):
            if field.name in cli_args and cli_args[field.name] is not None:
                values[field.name] = cli_args[field.name]

    # Verify all required fields are present
    missing = [field.name for field in fields(Config) if field.name not in values]
    if missing:
        msg = f"Missing required configuration: {', '.join(missing)}"
        raise ValueError(msg)

    # Confirm path fields are valid and construct Config
    hints = typing.get_type_hints(Config)
    config_kwargs: dict[str, str | Path] = {
        field.name: _confirm_path_exists(values[field.name]) if hints[field.name] is Path else values[field.name]
        for field in fields(Config)
    }
    return Config(**config_kwargs)  # type: ignore[arg-type]

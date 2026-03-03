"""Configuration loading and validation for rcpond.

Provides a `Config` class which loads configuration from three sources, in order
of increasing precedence:

1. A .env file (if ``env_path`` is supplied)
2. Environment variables prefixed with ``RCPOND_`` (e.g. ``RCPOND_LLM_MODEL``)
3. Explicit CLI arguments passed as ``cli_args``

Values from a higher-precedence source always override lower-precedence ones.
A ``ValueError`` is raised if any required field is still missing after all
sources are merged, or if a path field does not exist on disk.

The constructor implements some basic validation of parameters, specifically
ensuring that the file paths are valid.
"""

import os
import typing
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    """Validated runtime configuration for rcpond.

    Parameters
    ----------
    env_path : Path | None
        Path to a .env file to load. If None, no .env file is read.
    cli_args : dict | None
        Dict of config field names to values from the CLI. None values are ignored.

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

    env_path: InitVar[Path | None] = None
    cli_args: InitVar[dict | None] = None

    llm_base_url: str = field(init=False)
    llm_api_key: str = field(init=False)
    llm_model: str = field(init=False)
    servicenow_token: str = field(init=False)
    servicenow_url: str = field(init=False)
    rules_path: Path = field(init=False)
    system_prompt_template_path: Path = field(init=False)

    def __post_init__(self, env_path: Path | None, cli_args: dict | None) -> None:
        values: dict[str, str] = {}

        # 1. Load from .env file (lowest precedence)
        if env_path is not None:
            dotenv_vars = _parse_dotenv(env_path)
            for f in fields(self):
                env_key = _env_var_name(f.name)
                if env_key in dotenv_vars:
                    values[f.name] = dotenv_vars[env_key]

        # 2. Override with actual environment variables
        for f in fields(self):
            env_key = _env_var_name(f.name)
            if env_key in os.environ:
                values[f.name] = os.environ[env_key]

        # 3. Override with CLI args (highest precedence)
        if cli_args:
            for f in fields(self):
                if f.name in cli_args and cli_args[f.name] is not None:
                    values[f.name] = cli_args[f.name]

        # Verify all required fields are present
        missing = [f.name for f in fields(self) if f.name not in values]
        if missing:
            msg = f"Missing required configuration: {', '.join(missing)}"
            raise ValueError(msg)

        # Confirm path fields are valid and set attributes
        field_names = {f.name for f in fields(self)}
        hints = {k: v for k, v in typing.get_type_hints(Config).items() if k in field_names}
        for f in fields(self):
            value = _confirm_path_exists(values[f.name]) if hints[f.name] is Path else values[f.name]
            setattr(self, f.name, value)


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

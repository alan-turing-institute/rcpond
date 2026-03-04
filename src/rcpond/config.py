"""Configuration loading and validation for rcpond.

Provides class `Config` to read, parse, and make available
configuration variables required at runtime.  The constructor loads
configuration from:

1. A file (if ``env_path`` is supplied)
2. Environment variables prefixed with ``RCPOND_`` (e.g. ``RCPOND_LLM_MODEL``)
3. Explicit CLI arguments passed as ``cli_args``

Values from a later sources override earlier ones.  A ``ValueError``
is raised if any required field is still missing after all sources are
merged, or if a path field does not exist on disk.

The constructor implements some basic validation of parameters, specifically
ensuring that the file paths are valid.

File format
-----------

The format of the configuration file is, for example,
```
SERVICENOW_URL=https://turing-api.azure-api.net/dev-research/api/now/table
...
```

Example use
-----------

>>> the_config = Config("~/.config/rcpond/rcpond.txt")
>>> the_config.SERVICENOW_URL
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
    env_path : str | None
        Path to a .env file to load. If None, no .env file is read.
    cli_args : dict | None
        Dict of config field names to values from the CLI. None values are ignored.

    Attributes
    ----------
    llm_chat_completions_url : str
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

    env_path: InitVar[str | None] = None
    cli_args: InitVar[dict | None] = None

    llm_chat_completions_url: str = field(init=False)
    llm_api_key: str = field(init=False)
    llm_model: str = field(init=False)
    servicenow_token: str = field(init=False)
    servicenow_url: str = field(init=False)
    rules_path: Path = field(init=False)
    system_prompt_template_path: Path = field(init=False)

    def __post_init__(self, env_path: str | None, cli_args: dict | None) -> None:
        values: dict[str, str] = {}

        # 1. Load from .env file (lowest precedence)
        if env_path is not None:
            dotenv_vars = _parse_dotenv(_confirm_path_exists(env_path))
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

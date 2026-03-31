"""Configuration loading and validation for rcpond.

Provides class `Config` to read, parse, and make available
configuration variables required at runtime.  The constructor loads
configuration from:

1. The default file at $XDG_CONFIG_HOME/rcpond/default.config
2. A file (if ``env_path`` is supplied)
3. Environment variables prefixed with ``RCPOND_`` and uppercased (e.g. ``RCPOND_LLM_MODEL``)
4. Explicit CLI arguments passed as ``cli_args``

Values from a later sources override earlier ones.  A ``ValueError``
is raised if any required field is still missing after all sources are
merged, or if a path field does not exist on disk.

The constructor implements some basic validation of parameters, specifically
ensuring that the file paths are valid.

File format
-----------

The format of the configuration file is:
```
RCPOND_LLM_CHAT_COMPLETIONS_URL=...
RCPOND_LLM_API_KEY=your-api-key-here
RCPOND_LLM_MODEL=...
RCPOND_SERVICENOW_TOKEN=your-servicenow-token
RCPOND_SERVICENOW_URL=https://turing-api.azure-api.net/dev-research/api/now/table
RCPOND_RULES_PATH=/path/to/rule/file
RCPOND_SYSTEM_PROMPT_TEMPLATE_PATH=/path/to/prompt/file
```

Example use
-----------

>>> the_config = Config("/home/.config/rcpond/rcpond.txt")
>>> the_config.servicenow_token

"""

import os
import typing
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path

from xdg_base_dirs import xdg_config_home


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
    email_templates_path : Path
        Path of the directory of Jinja2 templates used to render messages to end users
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
    email_templates_dir: Path = field(init=False)

    def __post_init__(self, env_path: str | None, cli_args: dict | None) -> None:
        values: dict[str, str] = {}

        # 1. Load from $XDG_CONFIG_HOME/rcpond/default.config (lowest precedence)
        xdg_default = xdg_config_home() / "rcpond" / "default.config"
        if xdg_default.exists():
            xdg_vars = _parse_dotenv(xdg_default)
            for f in fields(self):
                env_key = _env_var_name(f.name)
                if env_key in xdg_vars:
                    values[f.name] = xdg_vars[env_key]

        # 2. Load from .env file
        if env_path is not None:
            dotenv_vars = _parse_dotenv(_confirm_path_exists(env_path))
            for f in fields(self):
                env_key = _env_var_name(f.name)
                if env_key in dotenv_vars:
                    values[f.name] = dotenv_vars[env_key]

        # 3. Override with actual environment variables
        for f in fields(self):
            env_key = _env_var_name(f.name)
            if env_key in os.environ:
                values[f.name] = os.environ[env_key]

        # 4. Override with CLI args (highest precedence)
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

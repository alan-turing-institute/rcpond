"""Configuration loading and validation for rcpond."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    servicenow_token: str
    servicenow_url: str
    rules_path: Path
    system_prompt_template_path: Path


def load_config() -> Config:
    """Load configuration from environment variables, .env file, and/or command-line params.

    Default values vs eror on missing values, precedence order and basic verification logic TBD.

    Returns
    -------
    Config
        The loaded and validated configuration.
    """
    # Load from .env file if present
    # Load from actual environment variables
    # Apply command-line param overrides
    # Verify required fields are present
    # Return populated Config dataclass

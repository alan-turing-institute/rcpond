from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    chat_completions_url: str
    api_key: str

"""Configuration loading for the council CLI."""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration loaded from environment."""
    
    database_url: str
    openrouter_api_key: str


class ConfigError(Exception):
    """Raised when required configuration is missing."""
    pass


def load_config(require_all: bool = True) -> Optional[Config]:
    """
    Load configuration from environment variables.
    
    Args:
        require_all: If True, raises ConfigError if required vars are missing.
                     If False, returns None for missing config.
    
    Returns:
        Config object if all required vars present, None if require_all=False and missing.
    
    Raises:
        ConfigError: If require_all=True and required vars are missing.
    """
    load_dotenv()
    
    database_url = os.environ.get("DATABASE_URL")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    
    missing = []
    if not database_url:
        missing.append("DATABASE_URL")
    if not openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    
    if missing:
        if require_all:
            raise ConfigError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please set them in your environment or create a .env file.\n"
                f"See .env.example for the required format."
            )
        return None
    
    return Config(
        database_url=database_url,
        openrouter_api_key=openrouter_api_key,
    )


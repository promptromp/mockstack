from functools import lru_cache
from typing import Any, Literal

from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for mockstack.

    Default values are defined below and can be overwritten using an .env file
    or with environment variables.

    """

    model_config = SettingsConfigDict(
        env_prefix="mockstack__",
        env_file=".env",
    )

    strategy: Literal["filefixtures", "chaosmonkey"] = "filefixtures"

    templates_dir: DirectoryPath = "./templates"

    # logging configuration. schema is based on the logging configuration schema:
    # https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
    logging: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "     %(levelname)s   [%(name)s] %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "DEBUG",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "FileFixturesStrategy": {
                "handlers": ["console"],
                "level": "DEBUG",
            },
        },
    }


@lru_cache
def settings_provider() -> Settings:
    """Provide the settings for the application."""
    return Settings()

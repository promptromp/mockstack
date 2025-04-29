from functools import lru_cache
from typing import Any, Literal

from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenTelemetrySettings(BaseSettings):
    """Settings for OpenTelemetry."""

    enabled: bool = False

    endpoint: str = "http://localhost:4317/"

    # whether to capture the response body.
    # this can be heavy, sensitive (PII) and/or not needed depending on the use case.
    capture_response_body: bool = False


class Settings(BaseSettings):
    """Settings for mockstack.

    Default values are defined below and can be overwritten using an .env file
    or with environment variables.

    """

    model_config = SettingsConfigDict(
        env_prefix="mockstack__",
        env_file=".env",
        env_nested_delimiter="__",
    )

    # OpenTelemetry configuration
    opentelemetry: OpenTelemetrySettings = OpenTelemetrySettings()

    # strategy to use for handling requests
    strategy: Literal["filefixtures", "proxyrules"] = "filefixtures"

    # base directory for templates used by strategies
    templates_dir: DirectoryPath = "./templates"  # type: ignore[assignment]

    # metadata fields to inject into created resources.
    # A few template fields are available. See documentation for more details.
    created_resource_metadata: dict[str, Any] = {
        "id": "{{ uuid4() }}",
        "createdAt": "{{ utcnow().isoformat() }}",
        "updatedAt": "{{ utcnow().isoformat() }}",
        "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
        "status": dict(code="OK", error_code=None),
    }

    # fields to inject into missing resources response json.
    # some services may require such additional fields to be present in the response.
    missing_resource_fields: dict[str, Any] = dict(
        code=404,
        message="mockstack: resource not found",
        retryable=False,
    )

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
                "level": "INFO",
            },
        },
    }


@lru_cache
def settings_provider() -> Settings:
    """Provide the settings for the application."""
    return Settings()

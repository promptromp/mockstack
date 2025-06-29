from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import DirectoryPath, FilePath, model_validator
from pydantic_settings import (
    BaseSettings,
    CliImplicitFlag,
    CliSuppress,
    SettingsConfigDict,
)

from mockstack.constants import (
    ENV_FILE,
    ENV_NESTED_DELIMITER,
    ENV_PREFIX,
    ProxyRulesRedirectVia,
)


class OpenTelemetrySettings(BaseSettings):
    """Settings for OpenTelemetry."""

    enabled: CliImplicitFlag[bool] = False

    endpoint: str = "http://localhost:4317/"

    # whether to capture the response body.
    # this can be heavy, sensitive (PII) and/or not needed depending on the use case.
    capture_response_body: CliImplicitFlag[bool] = False


class Settings(BaseSettings):
    """Settings for mockstack.

    Default values are defined below and can be overwritten using an .env file
    or with environment variables.

    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
    )

    # whether to run in debug mode
    debug: CliImplicitFlag[bool] = False

    # host to run the server on
    host: str = "0.0.0.0"

    # port to run the server on
    port: int = 8000

    # OpenTelemetry configuration
    opentelemetry: OpenTelemetrySettings = OpenTelemetrySettings()

    # strategy to use for handling requests
    strategy: Literal["filefixtures", "proxyrules"] = "filefixtures"

    # base directory for templates used by strategies
    templates_dir: DirectoryPath | None = None  # type: ignore[assignment]

    # whether to enable templates for POST requests.
    # By default, templates are not used for POSTs, and instead we try to
    # simulate a create (or search) operation. If turned on, we will first
    # try to materialize a template for the response, and if that fails
    # with a 404, we will then try to simulate creation of the resource.
    filefixtures_enable_templates_for_post: CliImplicitFlag[bool] = True

    # rules filename for proxyrules strategy
    proxyrules_rules_filename: FilePath | None = None  # type: ignore[assignment]

    # controls behavior of proxying. Whether to use HTTP status code redirects
    # or reverse proxy the request to the target URL "silently".
    proxyrules_redirect_via: ProxyRulesRedirectVia = ProxyRulesRedirectVia.REVERSE_PROXY

    # default timeout for reverse proxy requests. given in seconds. None disables timeouts.
    proxyrules_reverse_proxy_timeout: float | None = 10.0

    # controls behavior of proxying. Whether to simulate creation of resources
    # when a POST request is made to a resource that doesn't match any rules..
    proxyrules_simulate_create_on_missing: CliImplicitFlag[bool] = False

    # controls behavior of proxying. Whether to verify SSL certificates.
    # this is useful for testing against services that use self-signed certificates.
    # disable with caution!
    proxyrules_verify_ssl_certificates: CliImplicitFlag[bool] = True

    # metadata fields to inject into created resources.
    # A few template fields are available. See documentation for more details.
    created_resource_metadata: CliSuppress[dict[str, Any]] = {
        "id": "{{ uuid4() }}",
        "createdAt": "{{ utcnow().isoformat() }}",
        "updatedAt": "{{ utcnow().isoformat() }}",
        "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
        "status": dict(code="OK", error_code=None),
    }

    # fields to inject into missing resources response json.
    # some services may require such additional fields to be present in the response.
    missing_resource_fields: CliSuppress[dict[str, Any]] = dict(
        code=404,
        message="mockstack: resource not found",
        retryable=False,
    )

    # logging configuration. schema is based on the logging configuration schema:
    # https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
    logging: CliSuppress[dict[str, Any]] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "rich.logging.RichHandler",
                "level": "INFO",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console"],
                "level": "DEBUG",
                "propagate": False,
            },
            "FileFixturesStrategy": {
                "handlers": ["console"],
                "level": "DEBUG",
                "propagate": False,
            },
            "ProxyRulesStrategy": {
                "handlers": ["console"],
                "level": "DEBUG",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "NOTSET",
            "propagate": False,
        },
    }

    @model_validator(mode="after")
    def validate_strategy_parameters(self) -> Self:
        """Validate the strategy parameters."""

        # TODO: make this validation dynamic based on the strategy classes themselves.

        if self.strategy == "proxyrules":
            if self.proxyrules_rules_filename is None:
                raise ValueError(
                    "proxyrules_rules_filename is required when strategy is proxyrules"
                )

        elif self.strategy == "filefixtures":
            if self.templates_dir is None:
                raise ValueError(
                    "templates_dir is required when strategy is proxyrules"
                )

        return self


# Nb. We separate the Cli-specific parameters since currently breaks pytest
# when running via pre-commit hooks. Can remove once fixed by pytest / pre-commit.


class CliSettings(Settings):
    """Settings for mockstack CLI."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        cli_parse_args=True,
        cli_kebab_case=True,
        cli_hide_none_type=True,
        cli_avoid_json=True,
    )


@lru_cache
def settings_provider() -> Settings:
    """Provide the settings for the application."""
    return Settings()

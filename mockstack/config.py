from collections.abc import Callable
from functools import lru_cache
from string import Formatter
from typing import Any, Literal, Self

from pydantic import DirectoryPath, FilePath, ImportString, model_validator
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
    ProxyRulesRecordMode,
    ProxyRulesRedirectVia,
)


# Attribute docstrings become the settings' descriptions, which `mockstack --help` shows.


class SettingsDependencyError(ValueError):
    """A setting that another setting's value requires or rules out.

    ``template`` names each setting in braces, e.g. ``"{templates_dir} is required when
    {strategy} is filefixtures"``. The message names the settings as they are spelled in
    Python; the command line renders the template with flags instead (``mockstack.cli``).
    """

    def __init__(self, template: str) -> None:
        self.template = template
        self.settings = tuple(field for _, field, _, _ in Formatter().parse(template) if field)
        super().__init__(template.format_map({name: name for name in self.settings}))


class OpenTelemetrySettings(BaseSettings):
    """Settings for OpenTelemetry."""

    model_config = SettingsConfigDict(use_attribute_docstrings=True)

    enabled: CliImplicitFlag[bool] = False
    """Whether to enable the OpenTelemetry integration."""

    endpoint: str = "http://localhost:4317/"
    """OpenTelemetry endpoint to export traces to."""

    capture_response_body: CliImplicitFlag[bool] = False
    """Whether to capture response bodies in traces. Bodies can be large or contain sensitive data."""


class Settings(BaseSettings):
    """Settings for mockstack.

    Default values are defined below and can be overwritten using an .env file
    or with environment variables.

    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        use_attribute_docstrings=True,
    )

    debug: CliImplicitFlag[bool] = False
    """Whether to run in debug mode."""

    host: str = "0.0.0.0"  # noqa: S104
    """Host to run the server on. The default, every interface, makes the server reachable from outside a
    container."""

    port: int = 8000
    """Port to run the server on."""

    openapi_docs_enabled: CliImplicitFlag[bool] = False
    """Whether to serve FastAPI's documentation routes (/docs, /redoc, /openapi.json and
    /docs/oauth2-redirect). They take precedence over the catch-all route, so they are off by default and
    those paths reach the strategy like any other."""

    opentelemetry: OpenTelemetrySettings = OpenTelemetrySettings()
    """OpenTelemetry configuration."""

    strategy: Literal["filefixtures", "proxyrules"] = "filefixtures"
    """Strategy for handling requests: filefixtures renders templates from --templates-dir, proxyrules follows
    the rules in --proxyrules-rules-filename."""

    templates_dir: DirectoryPath | None = None
    """Existing directory of the templates the filefixtures strategy renders. Required when the strategy is
    filefixtures."""

    filefixtures_enable_templates_for_post: CliImplicitFlag[bool] = True
    """Whether a POST request tries a template before resource creation (or search) is simulated. A POST with
    no matching template is still simulated."""

    filefixtures_simulate_create_on_missing: CliImplicitFlag[bool] = True
    """Whether a create-looking POST with no matching template (or with templates for POST off) gets a
    simulated create. When disabled, it gets the same 404 as a GET with no template."""

    proxyrules_rules_filename: FilePath | None = None
    """Existing YAML rules file for the proxyrules strategy, validated at startup. Required when the strategy
    is proxyrules."""

    proxyrules_redirect_via: ProxyRulesRedirectVia = ProxyRulesRedirectVia.REVERSE_PROXY
    """What a rule whose replacement is a URL does: reverse proxy the request, or answer with an HTTP
    redirect."""

    proxyrules_reverse_proxy_timeout: float | None = 10.0
    """Timeout in seconds for reverse-proxied upstream requests. None disables the timeout."""

    proxyrules_simulate_create_on_missing: CliImplicitFlag[bool] = False
    """Whether a create-looking request (e.g. a POST) that matches no rule gets a simulated create instead of
    a 404."""

    proxyrules_verify_ssl_certificates: CliImplicitFlag[bool] = True
    """Whether to verify the TLS certificates of HTTPS upstreams. Disable with caution, e.g. for a trusted
    upstream with a self-signed certificate."""

    proxyrules_record_mode: ProxyRulesRecordMode = ProxyRulesRecordMode.OFF
    """Record mode: write upstream responses into the fixture files that fixture rules serve. missing records
    fixture files that do not exist yet; overwrite also re-records files recorded before. Never enable on a
    shared or exposed instance."""

    proxyrules_record_root: DirectoryPath | None = None
    """Existing directory that every recorded fixture file must resolve inside. Required when
    --proxyrules-record-mode is not off."""

    # pydantic also accepts "module.function".
    proxyrules_record_scrubber: ImportString[Callable[..., Any]] | None = None
    """Optional module:function called with every body before it is recorded. It returns the text to write,
    or None to skip recording that response. It is imported when settings load, so a bad reference stops
    mockstack from starting."""

    created_resource_metadata: CliSuppress[dict[str, Any]] = {
        "id": "{{ uuid4() }}",
        "createdAt": "{{ utcnow().isoformat() }}",
        "updatedAt": "{{ utcnow().isoformat() }}",
        "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
        "status": {"code": "OK", "error_code": None},
    }
    """Metadata fields to inject into created resources. A few template fields are available; see the
    documentation."""

    missing_resource_fields: CliSuppress[dict[str, Any]] = {
        "code": 404,
        "message": "mockstack: resource not found",
        "retryable": False,
    }
    """Fields to inject into the JSON of a missing resource response, for services that require them."""

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
    """Logging configuration, in the schema of
    https://docs.python.org/3/library/logging.config.html#logging-config-dictschema"""

    @model_validator(mode="after")
    def validate_strategy_parameters(self) -> Self:
        """Validate the strategy parameters."""

        # TODO: make this validation dynamic based on the strategy classes themselves.

        if self.strategy == "proxyrules" and self.proxyrules_rules_filename is None:
            raise SettingsDependencyError("{proxyrules_rules_filename} is required when {strategy} is proxyrules")

        if self.strategy == "filefixtures" and self.templates_dir is None:
            raise SettingsDependencyError("{templates_dir} is required when {strategy} is filefixtures (the default)")

        if self.strategy == "proxyrules" and self.proxyrules_record_mode != ProxyRulesRecordMode.OFF:
            if self.proxyrules_record_root is None:
                raise SettingsDependencyError(
                    "{proxyrules_record_root} is required when {proxyrules_record_mode} is not off"
                )
            if self.proxyrules_redirect_via != ProxyRulesRedirectVia.REVERSE_PROXY:
                raise SettingsDependencyError(
                    "{proxyrules_record_mode} requires {proxyrules_redirect_via} to be reverse_proxy"
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

"""OpenTelemetry integration.

The OpenTelemetry packages are the optional ``opentelemetry`` extra, so this module does
not import them: ``opentelemetry_provider`` loads ``mockstack.tracing``, which does, only
when the integration is enabled. Strategies add attributes to ``current_span(request)``,
which records nothing unless tracing is on.
"""

from typing import Any, Protocol

from fastapi import FastAPI, Request

from mockstack.config import Settings


OPENTELEMETRY_EXTRA = "mockstack[opentelemetry]"


class SpanLike(Protocol):
    """The part of an OpenTelemetry span that mockstack uses."""

    def set_attribute(self, key: str, value: Any) -> None: ...


class NullSpan:
    """A span that records nothing, for requests served without tracing."""

    def set_attribute(self, key: str, value: Any) -> None:
        """Discard the attribute."""


NULL_SPAN = NullSpan()


class OpenTelemetryUnavailableError(RuntimeError):
    """OpenTelemetry is enabled, but the optional packages it needs are not installed."""

    def __init__(self, missing_module: str) -> None:
        self.missing_module = missing_module
        super().__init__(
            f"OpenTelemetry is enabled, but its packages are not installed (no module named {missing_module!r}); "
            f"install them with: pip install '{OPENTELEMETRY_EXTRA}'"
        )


def current_span(request: Request) -> SpanLike:
    """The request's span: the tracing middleware's span, or ``NULL_SPAN`` without tracing."""
    span: SpanLike = getattr(request.state, "span", NULL_SPAN)
    return span


def opentelemetry_provider(app: FastAPI, settings: Settings) -> None:
    """Trace ``app``'s requests when OpenTelemetry is enabled.

    Raises ``OpenTelemetryUnavailableError`` when it is enabled but the ``opentelemetry``
    extra is not installed.
    """
    if not settings.opentelemetry.enabled:
        return

    try:
        # Imported here: the OpenTelemetry packages are optional and only needed when enabled.
        from mockstack import tracing  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        # Only a missing OpenTelemetry package means the extra is not installed; anything
        # else missing is a broken environment and keeps its traceback.
        if exc.name is None or not (exc.name == "opentelemetry" or exc.name.startswith("opentelemetry.")):
            raise
        raise OpenTelemetryUnavailableError(exc.name) from exc

    tracing.install(app, settings)

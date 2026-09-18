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
    """OpenTelemetry is enabled, but the optional packages it needs do not import.

    ``problem`` says why: the packages are not installed at all, or ``cause``, the
    ``ImportError`` raised by an incomplete install or mismatched versions.
    """

    def __init__(self, cause: ImportError) -> None:
        self.cause = cause
        if isinstance(cause, ModuleNotFoundError) and cause.name == "opentelemetry":
            self.problem = "the OpenTelemetry packages are not installed"
        else:
            self.problem = f"the OpenTelemetry packages cannot be imported: {cause}"
        super().__init__(
            f"OpenTelemetry is enabled, but {self.problem}; install them with: pip install '{OPENTELEMETRY_EXTRA}'"
        )


def current_span(request: Request) -> SpanLike:
    """The request's span: the tracing middleware's span, or ``NULL_SPAN`` without tracing."""
    span: SpanLike = getattr(request.state, "span", NULL_SPAN)
    return span


def opentelemetry_provider(app: FastAPI, settings: Settings) -> None:
    """Trace ``app``'s requests when OpenTelemetry is enabled.

    Raises ``OpenTelemetryUnavailableError`` when it is enabled but the ``opentelemetry``
    extra is not installed, or is incomplete.
    """
    if not settings.opentelemetry.enabled:
        return

    try:
        # Imported here: the OpenTelemetry packages are optional and only needed when enabled.
        from mockstack import tracing  # noqa: PLC0415
    except ImportError as exc:
        # mockstack's own modules are imported already, so any other import that fails is
        # the extra's: missing, incomplete (e.g. without grpc) or at mismatched versions.
        # A mockstack module that does not import is a bug and keeps its traceback.
        if exc.name is not None and (exc.name == "mockstack" or exc.name.startswith("mockstack.")):
            raise
        raise OpenTelemetryUnavailableError(exc) from exc

    tracing.install(app, settings)

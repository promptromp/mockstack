"""Display and logging functionality."""

import logging
from importlib import metadata

from fastapi import FastAPI

from mockstack.config import Settings


def announce(app: FastAPI, settings: Settings):
    """Log the startup message with the active settings."""
    logger = logging.getLogger("uvicorn")
    extra = {"markup": True}

    version = metadata.version("mockstack")

    logger.info(
        "[bold medium_purple]mockstack[/bold medium_purple] ready to roll. "
        "version: [medium_purple]%s[/medium_purple]. "
        "debug: [medium_purple]%s[/medium_purple]. "
        "strategy: [medium_purple]%s[/medium_purple]. ",
        version,
        settings.debug,
        settings.strategy,
        extra=extra,
    )
    logger.info(str(app.state.strategy), extra=extra)
    logger.info(
        "[medium_purple]OpenTelemetry[/medium_purple] enabled: [medium_purple]%s[/medium_purple],\n "
        "endpoint: [medium_purple]%s[/medium_purple],\n "
        "capture_response_body: [medium_purple]%s[/medium_purple]",
        settings.opentelemetry.enabled,
        settings.opentelemetry.endpoint,
        settings.opentelemetry.capture_response_body,
        extra=extra,
    )

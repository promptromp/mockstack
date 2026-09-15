"""Display and logging functionality."""

import logging
from importlib import metadata

from fastapi import FastAPI

from mockstack.config import Settings
from mockstack.constants import ProxyRulesRecordMode


def announce(app: FastAPI, settings: Settings) -> None:
    """Log the startup message with the active settings.

    This runs from the FastAPI lifespan, after ``dictConfig`` has applied the
    configured logging (see ``lifespan_provider``), so a WARNING logged here reaches
    the configured handlers -- unlike one logged while the strategy is constructed in
    ``create_app``, which runs earlier, before logging is configured.
    """
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

    if settings.strategy == "proxyrules" and settings.proxyrules_record_mode != ProxyRulesRecordMode.OFF:
        logger.warning(
            "proxyrules record mode %r is on: fixture files under %s are written from upstream responses",
            str(settings.proxyrules_record_mode),
            settings.proxyrules_record_root,
            extra=extra,
        )

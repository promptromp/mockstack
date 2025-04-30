"""Display and logging functionality."""

import logging

from fastapi import FastAPI

from mockstack.config import Settings


class ANSIColors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def announce(app: FastAPI, settings: Settings):
    """Log the startup message with the active settings."""
    HIGHLIGHT = ANSIColors.HEADER
    ENDC = ANSIColors.ENDC

    logger = logging.getLogger("uvicorn")
    logger.info(
        f"{HIGHLIGHT}mockstack{ENDC} ready to roll. "
        f"Using strategy: {HIGHLIGHT}{settings.strategy}{ENDC}, "
    )
    logger.info(str(app.state.strategy))
    logger.info(
        f"OpenTelemetry enabled: {HIGHLIGHT}{settings.opentelemetry.enabled}{ENDC}, "
        f"endpoint: {HIGHLIGHT}{settings.opentelemetry.endpoint}{ENDC}, "
        f"capture_response_body: {HIGHLIGHT}{settings.opentelemetry.capture_response_body}{ENDC}"
    )

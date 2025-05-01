"""FastAPI application lifecycle management."""

from contextlib import asynccontextmanager
from logging import DEBUG, config
from typing import Callable

from fastapi import FastAPI

from mockstack.config import Settings
from mockstack.display import announce


def logging_dict_config_from(settings: Settings) -> dict:
    """Get the logging config from the settings."""

    def enable_debug_logging(settings: Settings):
        """Enable verbose debug logging."""
        settings.logging["handlers"]["console"]["level"] = DEBUG

    if settings.debug:
        # Enable verbose debug logging if debug mode is set.
        enable_debug_logging(settings)

    return settings.logging


def lifespan_provider(
    settings: Settings,
) -> Callable:
    """Provide the lifespan context manager."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """FastAPI application lifespan management.

        This is the context manager that FastAPI will use to manage the lifecycle of the application.
        """

        config.dictConfig(logging_dict_config_from(settings))

        announce(app, settings)

        yield

    return lifespan

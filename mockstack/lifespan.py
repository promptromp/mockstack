"""FastAPI application lifecycle management."""

from logging import config

from contextlib import asynccontextmanager
from typing import Callable
from fastapi import FastAPI

from mockstack.display import announce
from mockstack.config import Settings


def lifespan_provider(
    settings: Settings,
) -> Callable:
    """Provide the lifespan context manager."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """FastAPI application lifespan management.

        This is the context manager that FastAPI will use to manage the lifecycle of the application.
        """
        config.dictConfig(settings.logging)
        announce(settings)

        yield

    return lifespan

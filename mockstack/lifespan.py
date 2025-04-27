"""FastAPI application lifecycle management."""

from contextlib import asynccontextmanager
from typing import Callable, AsyncGenerator
from fastapi import FastAPI

from mockstack.display import announce
from mockstack.config import Settings


def lifespan_provider(
    settings: Settings,
) -> Callable[[FastAPI], AsyncGenerator[None, None]]:
    """Provide the lifespan context manager."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """FastAPI application lifespan management.

        This is the context manager that FastAPI will use to manage the lifecycle of the application.
        """
        announce(settings)

        yield

    return lifespan

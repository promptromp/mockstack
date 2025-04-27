"""Factory for creating strategies."""

from fastapi import FastAPI

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.filefixtures import FileFixturesStrategy


def strategy_provider(app: FastAPI, settings: Settings) -> BaseStrategy:
    """Factory for creating strategies."""

    if settings.strategy == "filefixtures":
        strategy = FileFixturesStrategy(settings)
    else:
        raise ValueError(f"Unknown strategy: {settings.strategy}")

    # add strategy to app state for dependency injection
    app.state.strategy = strategy

    return strategy

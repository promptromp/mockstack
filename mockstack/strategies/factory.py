"""Factory for creating strategies."""

from typing import Type

from fastapi import FastAPI

from mockstack.config import Settings
from mockstack.strategies import BaseStrategy


def name_for(cls: type[BaseStrategy]) -> str:
    """Get the name of a strategy from its class.

    we support class attributes for the name, otherwise we use the class name
    without the "Strategy" suffix and convert to lowercase:

    Example:

    >>> name_for(FileFixturesStrategy)
    "filefixtures"

    """
    return getattr(cls, "name", cls.__name__.replace("Strategy", "").lower())


def available_strategies() -> dict[str, Type[BaseStrategy]]:
    """Get all available strategies."""
    return {name_for(subclass): subclass for subclass in BaseStrategy.__subclasses__()}  # type: ignore[type-abstract]


def strategy_provider(app: FastAPI, settings: Settings) -> BaseStrategy:
    """Factory for creating strategies."""
    strategies = available_strategies()

    if settings.strategy not in strategies:
        raise ValueError(f"Unknown strategy: {settings.strategy}")

    strategy = strategies[settings.strategy](settings)

    # add strategy to app state for dependency injection
    app.state.strategy = strategy

    return strategy


AVAILABLE_STRATEGIES = tuple(available_strategies().keys())

DEFAULT_STRATEGY = "filefixtures"

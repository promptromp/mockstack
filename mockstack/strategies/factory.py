"""Factory for creating strategies."""

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.filefixtures import FileFixturesStrategy


def strategy_provider(settings: Settings) -> BaseStrategy:
    """Factory for creating strategies."""
    if settings.strategy == "filefixtures":
        return FileFixturesStrategy(settings)
    else:
        raise ValueError(f"Unknown strategy: {settings.strategy}")

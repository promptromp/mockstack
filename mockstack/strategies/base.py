"""Base strategy for MockStack."""

from abc import ABC, abstractmethod

from fastapi import Request, Response

from mockstack.config import Settings


class BaseStrategy(ABC):
    """Base strategy for MockStack."""

    def __init__(self, settings: Settings, *args, **kwargs):
        self.settings = settings

    @abstractmethod
    async def apply(self, request: Request) -> Response:
        """Apply the strategy to the request and response."""
        pass

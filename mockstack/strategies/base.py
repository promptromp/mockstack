"""Base strategy for MockStack."""

from abc import ABC, abstractmethod

from fastapi import Request, Response


class BaseStrategy(ABC):
    """Base strategy for MockStack."""

    @abstractmethod
    async def apply(self, request: Request) -> Response:
        """Apply the strategy to the request and response."""
        pass

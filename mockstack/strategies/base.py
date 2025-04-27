"""Base strategy for MockStack."""

from abc import ABC, abstractmethod

from fastapi import Request, Response


class BaseStrategy(ABC):
    """Base strategy for MockStack."""

    @abstractmethod
    def apply(self, request: Request, response: Response | None = None) -> None:
        """Apply the strategy to the request and response."""
        pass

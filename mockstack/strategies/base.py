"""Base strategy for MockStack."""

from abc import ABC, abstractmethod
from typing import Any

from fastapi import Request, Response

from mockstack.config import Settings


class BaseStrategy(ABC):
    """Base strategy for MockStack."""

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        self.settings = settings

    @abstractmethod
    async def apply(self, request: Request) -> Response:
        """Apply the strategy to the request and response."""

    # An optional hook rather than an abstract method: a no-op unless a strategy overrides it.
    def update_opentelemetry(self, request: Request, *args: Any, **kwargs: Any) -> None:  # noqa: B027
        """Update the opentelemetry span with strategy-specific attributes.

        Add attributes to ``mockstack.telemetry.current_span(request)``. When OpenTelemetry
        is not enabled, that span records nothing.

        """

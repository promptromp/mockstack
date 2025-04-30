"""Strategy for using proxy rules."""

import logging

from fastapi import Request, Response, status

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy


class ProxyRulesStrategy(BaseStrategy):
    """Strategy for using proxy rules."""

    logger = logging.getLogger("ProxyRulesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rules = settings.proxy_rules

    async def apply(self, request: Request) -> Response:
        return Response(status_code=status.HTTP_200_OK)

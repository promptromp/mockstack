"""Strategy for using proxy rules."""

import logging
import re
from typing import Self

import yaml
from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy


class Rule:
    """A rule for the proxy rules strategy."""

    def __init__(self, pattern: str, replacement: str, method: str | None = None):
        self.pattern = pattern
        self.replacement = replacement
        self.method = method

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Self:
        return cls(
            pattern=data["pattern"],
            replacement=data["replacement"],
            method=data.get("method", None),
        )

    def matches(self, request: Request) -> bool:
        """Check if the rule matches the request."""
        if self.method is not None and request.method.lower() != self.method.lower():
            # if rule is limited to a specific HTTP method, validate first.
            return False

        return re.match(self.pattern, request.url.path) is not None

    def apply(self, request: Request) -> Response:
        """Apply the rule to the request."""
        url = self._url_for(request.url.path)
        return RedirectResponse(url=url)

    def _url_for(self, path: str) -> str:
        return re.sub(self.pattern, self.replacement, path)


class ProxyRulesStrategy(BaseStrategy):
    """Strategy for using proxy rules."""

    logger = logging.getLogger("ProxyRulesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self.rules_filename = settings.proxyrules_rules_filename

    @property
    def rules(self) -> list[Rule]:
        if not hasattr(self, "_rules"):
            self._rules = self.load_rules()
        return self._rules

    def load_rules(self) -> list[Rule]:
        if self.rules_filename is None:
            raise ValueError("rules_filename is not set")

        with open(self.rules_filename, "r") as file:
            data = yaml.safe_load(file)
            return [Rule.from_dict(rule) for rule in data["rules"]]

    def rule_for(self, request: Request) -> Rule | None:
        try:
            return next(rule for rule in self.rules if rule.matches(request))
        except StopIteration:
            return None

    async def apply(self, request: Request) -> Response:
        rule = self.rule_for(request)
        if rule is None:
            self.logger.warning(f"No rule found for request: {request.url.path=}")
            return Response(status_code=status.HTTP_404_NOT_FOUND)

        return rule.apply(request)

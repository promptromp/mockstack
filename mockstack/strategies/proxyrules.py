"""Strategy for using proxy rules."""

import logging
import re
from functools import cached_property
from typing import Self
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse
from jinja2 import Environment
from starlette.datastructures import Headers

from mockstack.config import Settings
from mockstack.constants import ProxyRulesRedirectVia
from mockstack.intent import looks_like_a_create
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.create_mixin import CreateMixin


class Rule:
    """A rule for the proxy rules strategy."""

    def __init__(
        self,
        pattern: str,
        replacement: str,
        method: str | None = None,
        name: str | None = None,
    ):
        self.pattern = pattern
        self.replacement = replacement
        self.method = method
        self.name = name

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Self:
        return cls(
            pattern=data["pattern"],
            replacement=data["replacement"],
            method=data.get("method", None),
            name=data.get("name", None),
        )

    def matches(self, request: Request) -> bool:
        """Check if the rule matches the request."""
        if self.method is not None and request.method.lower() != self.method.lower():
            # if rule is limited to a specific HTTP method, validate first.
            return False

        return re.match(self.pattern, request.url.path) is not None

    def apply(self, request: Request) -> str:
        """Apply the rule to the request."""
        return self._url_for(request.url.path)

    def _url_for(self, path: str) -> str:
        return re.sub(self.pattern, self.replacement, path)


class ProxyRulesStrategy(BaseStrategy, CreateMixin):
    """Strategy for using proxy rules."""

    logger = logging.getLogger("ProxyRulesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self.rules_filename = settings.proxyrules_rules_filename
        self.redirect_via = settings.proxyrules_redirect_via
        self.reverse_proxy_timeout = settings.proxyrules_reverse_proxy_timeout
        self.simulate_create_on_missing = settings.proxyrules_simulate_create_on_missing
        self.created_resource_metadata = settings.created_resource_metadata

        self.env = Environment()

    def __str__(self) -> str:
        return (
            f"[medium_purple]proxyrules[/medium_purple]\n "
            f"rules_filename: {self.rules_filename}.\n "
            f"redirect_via: [medium_purple]{self.redirect_via}[/medium_purple].\n "
            f"simulate_create_on_missing: {self.simulate_create_on_missing}.\n "
            f"reverse_proxy_timeout: {self.reverse_proxy_timeout}"
        )

    @cached_property
    def rules(self) -> list[Rule]:
        return self.load_rules()

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
            self.logger.warning(
                f"No rule found for request: {request.method} {request.url.path}"
            )

            if self.simulate_create_on_missing and looks_like_a_create(request):
                self.logger.info(
                    f"Simulating resource creation for missing rule for {request.method} {request.url.path}"
                )
                return await self._create(
                    request,
                    env=self.env,
                    created_resource_metadata=self.created_resource_metadata,
                )
            else:
                # no rule found and we are not simulating resource creation
                return Response(status_code=status.HTTP_404_NOT_FOUND)

        url = rule.apply(request)
        self.logger.info(f"Redirecting to: {url}")
        self.update_opentelemetry(request, rule, url)

        match self.redirect_via:
            case ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT:
                return RedirectResponse(
                    url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
                )

            case ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT:
                return RedirectResponse(
                    url=url, status_code=status.HTTP_301_MOVED_PERMANENTLY
                )

            case ProxyRulesRedirectVia.REVERSE_PROXY:
                response = await self.reverse_proxy(request, url)
                return response

            case _:
                raise ValueError(f"Invalid redirect via value: {self.redirect_via=}")

    async def reverse_proxy(self, request: Request, url: str) -> Response:
        """Reverse proxy the request to the target URL."""
        async with httpx.AsyncClient(timeout=self.reverse_proxy_timeout) as client:
            request_content = await request.body()
            request_headers = self.reverse_proxy_headers(request.headers, url=url)
            req = client.build_request(
                request.method,
                url,
                content=request_content,
                headers=request_headers,
                params=request.url.query,
            )

            resp = await client.send(req, stream=False)
            content = resp.read()

            return Response(
                content=content,
                status_code=resp.status_code,
                headers=resp.headers,
                media_type=resp.headers.get("content-type"),
            )

    def reverse_proxy_headers(self, headers: Headers, url: str) -> Headers:
        """Mutate the request headers for the reverse proxy mode."""
        _headers = headers.mutablecopy()

        # When reverse proxying, we must alter the Host header to the target URL.
        _headers["host"] = urlparse(url).netloc

        return _headers

    def update_opentelemetry(self, request: Request, rule: Rule, url: str) -> None:
        """Update the opentelemetry span with the proxy rules rule details."""
        span = request.state.span
        if rule.name is not None:
            span.set_attribute("mockstack.proxyrules.rule_name", rule.name)
        if rule.method is not None:
            span.set_attribute("mockstack.proxyrules.rule_method", rule.method)

        span.set_attribute("mockstack.proxyrules.rule_pattern", rule.pattern)
        span.set_attribute("mockstack.proxyrules.rule_replacement", rule.replacement)
        span.set_attribute("mockstack.proxyrules.rewritten_url", url)

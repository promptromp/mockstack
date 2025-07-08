"""Strategy for using proxy rules."""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from jinja2 import Environment
from starlette.datastructures import Headers

from mockstack.config import Settings
from mockstack.constants import PROXYRULES_FILE_TEMPLATE_PREFIX, ProxyRulesRedirectVia
from mockstack.intent import looks_like_a_create
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.create_mixin import CreateMixin
from mockstack.templating import (
    templates_env_provider,
    parse_template_name_segments_and_identifiers,
)


class RuleResult(ABC):
    """Base class for rule application results."""

    @abstractmethod
    def get_result_type(self) -> str:
        """Return the type of result."""
        pass


@dataclass
class URLRuleResult(RuleResult):
    """Result for URL-based rules."""

    url: str

    def get_result_type(self) -> str:
        return "url"


@dataclass
class TemplateRuleResult(RuleResult):
    """Result for template-based rules."""

    template_path: str
    template_context: dict

    def get_result_type(self) -> str:
        return "template"


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

    def apply(self, request: Request) -> RuleResult:
        """Apply the rule to the request."""
        path = request.url.path
        result = self._url_for(path)

        # Check if the replacement is a file template
        if result.startswith(PROXYRULES_FILE_TEMPLATE_PREFIX):
            # Extract the file path from the file:/// URL
            file_path = result[len(PROXYRULES_FILE_TEMPLATE_PREFIX) - 1 :]

            # Create template context from request
            template_context = self._create_template_context(request)

            return TemplateRuleResult(
                template_path=file_path,
                template_context=template_context,
            )
        else:
            # Regular URL replacement
            return URLRuleResult(url=result)

    def _url_for(self, path: str) -> str:
        return re.sub(self.pattern, self.replacement, path)

    def _create_template_context(self, request: Request) -> dict:
        """Create template context from the request, using the same logic as templating.py."""
        path = request.url.path
        name_segments, identifiers = parse_template_name_segments_and_identifiers(
            path, default_identifier_key="id"
        )
        return {
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "path": request.url.path,
            "method": request.method,
            **identifiers,
        }


class ProxyRulesStrategy(BaseStrategy, CreateMixin):
    """Strategy for using proxy rules."""

    logger = logging.getLogger("ProxyRulesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self.created_resource_metadata = settings.created_resource_metadata
        self.missing_resource_fields = settings.missing_resource_fields
        self.redirect_via = settings.proxyrules_redirect_via
        self.reverse_proxy_timeout = settings.proxyrules_reverse_proxy_timeout
        self.rules_filename = settings.proxyrules_rules_filename
        self.simulate_create_on_missing = settings.proxyrules_simulate_create_on_missing
        self.verify_ssl_certificates = settings.proxyrules_verify_ssl_certificates

    def __str__(self) -> str:
        return (
            f"[medium_purple]proxyrules[/medium_purple]\n "
            f"rules_filename: {self.rules_filename}.\n "
            f"redirect_via: [medium_purple]{self.redirect_via}[/medium_purple].\n "
            f"simulate_create_on_missing: {self.simulate_create_on_missing}.\n "
            f"reverse_proxy_timeout: {self.reverse_proxy_timeout}\n "
            f"verify_ssl_certificates: {self.verify_ssl_certificates}\n "
        )

    @cached_property
    def env(self) -> Environment:
        """Jinja2 environment for the proxy rules strategy."""
        return templates_env_provider()

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
            return await self.handle_missing_rule(request)

        result = rule.apply(request)
        self.logger.info(f"[rule:{rule.name}] Result: {result}")

        # Handle template results
        if isinstance(result, TemplateRuleResult):
            return await self.handle_template_result(request, rule, result)
        elif isinstance(result, URLRuleResult):
            return await self.handle_url_result(request, rule, result)
        else:
            raise ValueError(f"Unknown result type: {type(result)}")

    async def handle_missing_rule(self, request: Request) -> Response:
        """Handle a missing rule."""
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
            return JSONResponse(
                content=self.missing_resource_fields,
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def handle_url_result(
        self, request: Request, rule: Rule, result: URLRuleResult
    ) -> Response:
        """Handle URL results by redirecting to the target URL."""
        self.update_opentelemetry(request, rule, result.url)

        match self.redirect_via:
            case ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT:
                return RedirectResponse(
                    url=result.url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
                )

            case ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT:
                return RedirectResponse(
                    url=result.url, status_code=status.HTTP_301_MOVED_PERMANENTLY
                )

            case ProxyRulesRedirectVia.REVERSE_PROXY:
                response = await self.reverse_proxy(request, result.url)
                return response

            case _:
                raise ValueError(f"Invalid redirect via value: {self.redirect_via=}")

    async def handle_template_result(
        self, request: Request, rule: Rule, result: TemplateRuleResult
    ) -> Response:
        """Handle template results by rendering the template file."""
        template_path = Path(result.template_path)

        if not template_path.exists():
            self.logger.error(f"Template file not found: {template_path}")
            return JSONResponse(
                content={"error": f"Template file not found: {template_path}"},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            # Read the template file content
            with open(template_path, "r") as f:
                template_content = f.read()

            # Create a template from the content
            template = self.env.from_string(template_content)

            # Render the template with context
            rendered_content = template.render(**result.template_context)

            # Determine content type based on file extension
            content_type = self._get_content_type(template_path)

            # Update opentelemetry with template info
            self.update_opentelemetry_template(request, rule, result)

            return Response(
                content=rendered_content,
                media_type=content_type,
                status_code=status.HTTP_200_OK,
            )

        except Exception as e:
            self.logger.error(f"Error rendering template {template_path}: {e}")
            return JSONResponse(
                content={
                    "error": "An internal error occurred while rendering the template."
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    async def reverse_proxy(self, request: Request, url: str) -> Response:
        """Reverse proxy the request to the target URL."""
        async with httpx.AsyncClient(
            timeout=self.reverse_proxy_timeout, verify=self.verify_ssl_certificates
        ) as client:
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

    def _get_content_type(self, template_path: Path) -> str:
        """Determine content type based on file extension."""
        suffix = template_path.suffix.lower()
        content_types = {
            ".json": "application/json",
            ".xml": "application/xml",
            ".html": "text/html",
            ".txt": "text/plain",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
        }
        return content_types.get(suffix, "text/plain")

    def update_opentelemetry_template(
        self, request: Request, rule: Rule, result: TemplateRuleResult
    ) -> None:
        """Update the opentelemetry span with template-specific details."""
        span = request.state.span
        if rule.name is not None:
            span.set_attribute("mockstack.proxyrules.rule_name", rule.name)
        if rule.method is not None:
            span.set_attribute("mockstack.proxyrules.rule_method", rule.method)

        span.set_attribute("mockstack.proxyrules.rule_pattern", rule.pattern)
        span.set_attribute("mockstack.proxyrules.rule_replacement", rule.replacement)
        span.set_attribute("mockstack.proxyrules.template_path", result.template_path)
        span.set_attribute("mockstack.proxyrules.result_type", "template")

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

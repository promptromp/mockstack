"""Strategy for using proxy rules."""

import logging
from functools import cached_property
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from httpx import Headers as ResponseHeaders
from jinja2 import Environment
from starlette.datastructures import Headers

from mockstack.config import Settings
from mockstack.constants import (
    CONTENT_ENCODING_COMPRESSED,
    HOP_BY_HOP_HEADERS,
    RESULT_RULE_HEADER,
    RESULT_TYPE_HEADER,
    ProxyRulesRedirectVia,
)
from mockstack.intent import looks_like_a_create
from mockstack.rules import RequestPayload, Rule, TemplateRuleResult, URLRuleResult
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.create_mixin import CreateMixin
from mockstack.templating import templates_env_provider


def maybe_update_response_headers(
    response_headers: ResponseHeaders,
    *,
    content_length: int,
) -> ResponseHeaders:
    """Update the response headers if needed, e.g. to adjust for compression and framing."""
    _headers = response_headers.copy()

    for name in HOP_BY_HOP_HEADERS:
        _headers.pop(name, None)

    if _headers.get("content-encoding") in CONTENT_ENCODING_COMPRESSED:
        # httpx already decompressed the body while proxying.
        _headers["content-encoding"] = "identity"

    # We always return a fully buffered body, so the length is known.
    _headers["content-length"] = str(content_length)

    return _headers


def _header_safe(value: str) -> str:
    """Make an arbitrary string safe to use as an HTTP header value.

    Starlette encodes header values as latin-1, so a rule ``name``/``pattern``
    containing non-Latin-1 characters (e.g. CJK) would otherwise raise
    ``UnicodeEncodeError`` when the response is sent. CR/LF are also stripped
    (replaced with a space) since they are not valid inside a single header value.
    """
    value = value.replace("\r", " ").replace("\n", " ")
    return value.encode("ascii", "backslashreplace").decode("ascii")


def with_result_headers(
    response: Response, *, rule: Rule | None, result_type: str
) -> Response:
    """Stamp the response with which rule (if any) produced it and how."""
    response.headers[RESULT_TYPE_HEADER] = result_type
    if rule is not None:
        response.headers[RESULT_RULE_HEADER] = _header_safe(rule.name or rule.pattern)
    return response


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
            return [Rule.from_dict(rule, env=self.env) for rule in data["rules"]]

    def rule_for(
        self, request: Request, payload: RequestPayload | None = None
    ) -> Rule | None:
        try:
            return next(rule for rule in self.rules if rule.matches(request, payload))
        except StopIteration:
            return None

    async def apply(self, request: Request) -> Response:
        # Read the body exactly once. Starlette caches it on the request, so the
        # reverse proxy and create-mixin paths can safely read it again later.
        payload = RequestPayload.from_bytes(await request.body())

        rule = self.rule_for(request, payload)
        if rule is None:
            return await self.handle_missing_rule(request)

        result = rule.apply(request, payload)
        self.logger.info(f"[rule:{rule.name}] Result: {result}")

        # Handle template results
        if isinstance(result, TemplateRuleResult):
            response = await self.handle_template_result(request, rule, result)
            return with_result_headers(response, rule=rule, result_type="template")
        elif isinstance(result, URLRuleResult):
            response = await self.handle_url_result(request, rule, result)
            result_type = (
                "proxy"
                if self.redirect_via == ProxyRulesRedirectVia.REVERSE_PROXY
                else "redirect"
            )
            return with_result_headers(response, rule=rule, result_type=result_type)
        else:
            raise TypeError(f"Unknown result type: {type(result)}")

    async def handle_missing_rule(self, request: Request) -> Response:
        """Handle a missing rule."""
        self.logger.warning(
            f"No rule found for request: {request.method} {request.url.path}"
        )

        if self.simulate_create_on_missing and looks_like_a_create(request):
            self.logger.info(
                f"Simulating resource creation for missing rule for {request.method} {request.url.path}"
            )
            response = await self._create(
                request,
                env=self.env,
                created_resource_metadata=self.created_resource_metadata,
            )
            return with_result_headers(response, rule=None, result_type="create")
        else:
            response = JSONResponse(
                content=self.missing_resource_fields,
                status_code=status.HTTP_404_NOT_FOUND,
            )
            return with_result_headers(response, rule=None, result_type="missing")

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

        if ".." in template_path.parts:
            # A rendered `file://` path may be built (in part) from request-controlled
            # values (headers, query, path segments, body). Reject any path traversal
            # attempt rather than resolving and possibly reading a file outside the
            # fixtures the rule author intended. The path itself is not echoed back in
            # the response body, only to the log.
            self.logger.error(
                f"Rejected template path containing '..': {template_path}"
            )
            return JSONResponse(
                content={"error": "Template file not found."},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not template_path.exists():
            self.logger.error(f"Template file not found: {template_path}")
            return JSONResponse(
                content={"error": f"Template file not found: {template_path}"},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            # Read the template file content.
            # Templates are small local files read once per request; the sync
            # read is intentional here rather than adding an async-file dependency.
            with open(template_path, "r") as f:  # noqa: ASYNC230
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

        except Exception as e:  # noqa: BLE001 -- deliberate catch-all so template
            # rendering errors (e.g. Jinja2 errors) degrade to a 500 instead of crashing.
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

            response_headers = maybe_update_response_headers(
                resp.headers,
                content_length=len(content),
            )

            return Response(
                content=content,
                status_code=resp.status_code,
                headers=response_headers,
                media_type=response_headers.get("content-type"),
            )

    def reverse_proxy_headers(self, headers: Headers, url: str) -> Headers:
        """Mutate the request headers for the reverse proxy mode."""
        _headers = headers.mutablecopy()

        for name in (*HOP_BY_HOP_HEADERS, "content-length"):
            # We forward a fully buffered body; httpx sets the correct framing headers.
            if name in _headers:
                del _headers[name]

        # When reverse proxying, we must alter the Host header to the target URL.
        _headers["host"] = urlparse(url).netloc

        return _headers

    def _get_content_type(self, template_path: Path) -> str:
        """Determine content type from the file extension, ignoring a trailing ``.j2``."""
        if template_path.suffix.lower() == ".j2":
            template_path = template_path.with_suffix("")
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

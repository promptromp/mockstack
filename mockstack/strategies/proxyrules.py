"""Strategy for using proxy rules."""

import logging
import re
from functools import cached_property
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from httpx import Headers as ResponseHeaders
from jinja2 import Environment, TemplateSyntaxError
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect

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


class UpstreamError(Exception):
    """The reverse-proxied upstream could not be reached or did not answer in time."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


HeadersT = TypeVar("HeadersT", MutableHeaders, ResponseHeaders)


def strip_hop_by_hop(headers: HeadersT) -> HeadersT:
    """Remove hop-by-hop headers in place (RFC 9110 §7.6.1) and return ``headers``.

    That is every name in ``HOP_BY_HOP_HEADERS`` plus every header listed in a
    ``Connection`` header value. Works for both Starlette ``MutableHeaders`` and
    ``httpx.Headers``, whose ``items()`` both expose every ``Connection`` value.
    """
    listed: set[str] = {
        token.strip().lower()
        for name, value in headers.items()
        if name.lower() == "connection"
        for token in value.split(",")
    }
    listed.discard("")
    for name in (*HOP_BY_HOP_HEADERS, *sorted(listed)):
        if name in headers:
            del headers[name]
    return headers


def maybe_update_response_headers(
    response_headers: ResponseHeaders,
    *,
    content_length: int,
    status_code: int,
    request_method: str,
) -> ResponseHeaders:
    """Update the response headers if needed, e.g. to adjust for compression and framing."""
    _headers = response_headers.copy()
    strip_hop_by_hop(_headers)

    encoding = _headers.get("content-encoding")
    if encoding is not None:
        tokens = [t.strip() for t in encoding.lower().split(",") if t.strip()]
        if tokens and all(t in CONTENT_ENCODING_COMPRESSED for t in tokens):
            # httpx already decompressed the body while proxying.
            _headers["content-encoding"] = "identity"

    if status_code < 200 or status_code in (
        status.HTTP_204_NO_CONTENT,
        status.HTTP_304_NOT_MODIFIED,
    ):
        # RFC 9110 §8.6: a server MUST NOT send Content-Length on a 1xx or 204, and on
        # a 304 the value must be whatever the corresponding 200 would have carried --
        # ``0`` (the length of our empty buffered body) would be a lie. Drop any
        # inherited value rather than stamp one.
        _headers.pop("content-length", None)
    elif request_method.upper() == "HEAD":
        # A HEAD response has no body; the upstream's Content-Length describes the
        # representation a GET would return, so leave it (or its absence) untouched.
        pass
    else:
        # We always return a fully buffered body, so the length is known.
        _headers["content-length"] = str(content_length)

    return _headers


_CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _header_safe(value: str) -> str:
    """Make an arbitrary string safe to use as an HTTP header value.

    Starlette encodes header values as latin-1, so a rule ``name``/``pattern``
    containing non-Latin-1 characters (e.g. CJK) would otherwise raise
    ``UnicodeEncodeError`` when the response is sent. ASCII control characters
    (CR/LF included, but also e.g. NUL, VT, DEL) are also stripped (replaced with a
    space) since they are not valid inside a single header value and would otherwise
    survive ``backslashreplace`` as literal bytes that h11 rejects. Surrounding
    whitespace is trimmed, and an empty result falls back to ``"unnamed"``.
    """
    value = _CONTROL_CHARACTERS_RE.sub(" ", value).strip()
    return value.encode("ascii", "backslashreplace").decode("ascii") or "unnamed"


def with_result_headers(
    response: Response, *, rule: Rule | None, result_type: str
) -> Response:
    """Stamp the response with which rule (if any) produced it and how. Never raises."""
    response.headers[RESULT_TYPE_HEADER] = result_type
    if rule is not None:
        response.headers[RESULT_RULE_HEADER] = _header_safe(
            str(rule.name or rule.pattern)
        )
    return response


def _error_response(message: str, *, status_code: int, rule: Rule | None) -> Response:
    """A JSON error body stamped ``X-Mockstack-Result: error``."""
    return with_result_headers(
        JSONResponse(content={"error": message}, status_code=status_code),
        rule=rule,
        result_type="error",
    )


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

        if self.rules_filename is not None:
            # Load (and so validate) the rules now, so a bad rules file fails at
            # startup rather than on the first request.
            _ = self.rules

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
        return [self._rule_from_dict(rule) for rule in data["rules"]]

    def _rule_from_dict(self, data: dict[str, Any]) -> Rule:
        """Build one rule, naming it in any load-time validation error."""
        name = str(data["name"]) if data.get("name") is not None else None
        try:
            return Rule.from_dict(data, env=self.env)
        except re.error as exc:
            raise ValueError(
                f"rule {name!r}: invalid regex {exc.pattern!r}: {exc}"
            ) from exc
        except TemplateSyntaxError as exc:
            raise ValueError(
                f"rule {name!r}: invalid replacement template: {exc}"
            ) from exc

    def rule_for(
        self, request: Request, payload: RequestPayload | None = None
    ) -> Rule | None:
        try:
            return next(rule for rule in self.rules if rule.matches(request, payload))
        except StopIteration:
            return None

    async def apply(self, request: Request) -> Response:
        """Apply the proxyrules strategy to the request.

        Every response carries the ``X-Mockstack-*`` result headers, including the
        strategy's own error responses: an unreachable or slow upstream is a stamped
        502/504, and any other failure (e.g. a replacement referencing a missing
        header) a stamped 500, instead of a bare, unstamped 500 from Starlette's
        ``ServerErrorMiddleware``. A client that disconnected gets no answer.
        """
        rule: Rule | None = None
        try:
            # Read the body exactly once. Starlette caches it on the request, so the
            # reverse proxy and create-mixin paths can safely read it again later.
            payload = RequestPayload.from_bytes(await request.body())

            rule = self.rule_for(request, payload)
            if rule is None:
                return await self.handle_missing_rule(request)

            result = rule.apply(request, payload)
            if isinstance(result, TemplateRuleResult):
                self.logger.info(
                    f"[rule:{rule.name}] template result: {result.template_path}"
                )
                return await self.handle_template_result(request, rule, result)
            if isinstance(result, URLRuleResult):
                self.logger.info(f"[rule:{rule.name}] url result: {result.url}")
                return await self.handle_url_result(request, rule, result)
            raise TypeError(f"Unknown result type: {type(result)}")

        except ClientDisconnect:
            raise
        except UpstreamError as exc:
            self.logger.warning(
                f"[rule:{rule.name if rule else None}] {exc.message} for "
                f"{request.method} {request.url.path}: {exc.__cause__!r}"
            )
            return _error_response(exc.message, status_code=exc.status_code, rule=rule)
        except Exception:
            self.logger.exception(
                f"[rule:{rule.name if rule else None}] unhandled error applying "
                f"strategy to {request.method} {request.url.path}"
            )
            return _error_response(
                "mockstack: internal error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                rule=rule,
            )

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
                response: Response = RedirectResponse(
                    url=result.url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
                )
                return with_result_headers(response, rule=rule, result_type="redirect")

            case ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT:
                response = RedirectResponse(
                    url=result.url, status_code=status.HTTP_301_MOVED_PERMANENTLY
                )
                return with_result_headers(response, rule=rule, result_type="redirect")

            case ProxyRulesRedirectVia.REVERSE_PROXY:
                response = await self.reverse_proxy(request, result.url)
                return with_result_headers(response, rule=rule, result_type="proxy")

            case _:
                raise ValueError(f"Invalid redirect via value: {self.redirect_via=}")

    async def handle_template_result(
        self, request: Request, rule: Rule, result: TemplateRuleResult
    ) -> Response:
        """Handle template results by rendering the template file.

        Only a successful render is stamped ``template``; a missing fixture (404) or
        a failed render (500) is stamped ``error``. Neither echoes the rendered path,
        which may be built from request data, back to the client.
        """
        template_path = Path(result.template_path)

        if ".." in template_path.parts:
            # A rendered `file://` path may be built (in part) from request-controlled
            # values (headers, query, path segments, body). Reject any path traversal
            # attempt rather than resolving and possibly reading a file outside the
            # fixtures the rule author intended.
            self.logger.error(
                f"Rejected template path containing '..': {template_path}"
            )
            return _error_response(
                "Template file not found.",
                status_code=status.HTTP_404_NOT_FOUND,
                rule=rule,
            )

        if not template_path.exists():
            self.logger.error(f"Template file not found: {template_path}")
            return _error_response(
                "Template file not found.",
                status_code=status.HTTP_404_NOT_FOUND,
                rule=rule,
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

            response = Response(
                content=rendered_content,
                media_type=content_type,
                status_code=status.HTTP_200_OK,
            )
            return with_result_headers(response, rule=rule, result_type="template")

        except Exception as e:  # noqa: BLE001 -- deliberate catch-all so template
            # rendering errors (e.g. Jinja2 errors) degrade to a 500 instead of crashing.
            self.logger.error(f"Error rendering template {template_path}: {e}")
            return _error_response(
                "An internal error occurred while rendering the template.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                rule=rule,
            )

    async def reverse_proxy(self, request: Request, url: str) -> Response:
        """Reverse proxy the request to the target URL.

        Raises ``UpstreamError`` (504 on a timeout, 502 on any other transport or
        protocol failure) when the upstream cannot be reached.
        """
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

            try:
                resp = await client.send(req, stream=False)
            except httpx.TimeoutException as exc:
                raise UpstreamError(
                    status.HTTP_504_GATEWAY_TIMEOUT,
                    "mockstack: upstream request timed out",
                ) from exc
            except httpx.HTTPError as exc:
                raise UpstreamError(
                    status.HTTP_502_BAD_GATEWAY, "mockstack: upstream request failed"
                ) from exc
            content = resp.read()

        response_headers = maybe_update_response_headers(
            resp.headers,
            content_length=len(content),
            status_code=resp.status_code,
            request_method=request.method,
        )

        response = Response(
            content=content, status_code=resp.status_code, media_type=None
        )
        # Copy the upstream headers item by item (not via a mapping) so repeated
        # headers such as Set-Cookie survive. Starlette expects lower-cased names.
        response.raw_headers = [
            (name.lower(), value) for name, value in response_headers.raw
        ]
        return response

    def reverse_proxy_headers(self, headers: Headers, url: str) -> Headers:
        """Mutate the request headers for the reverse proxy mode."""
        _headers = headers.mutablecopy()
        strip_hop_by_hop(_headers)

        # We forward a fully buffered body; httpx sets the correct framing headers.
        if "content-length" in _headers:
            del _headers["content-length"]

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

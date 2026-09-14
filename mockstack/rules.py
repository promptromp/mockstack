"""Rules for the proxy rules strategy."""

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import quote

from fastapi import Request

from mockstack.constants import PROXYRULES_FILE_TEMPLATE_PREFIX
from mockstack.templating import parse_template_name_segments_and_identifiers


@dataclass(frozen=True)
class RequestPayload:
    """The request body, read exactly once by the strategy and shared with every rule.

    Keeping this separate from ``Request`` lets ``Rule.matches`` / ``Rule.apply`` stay
    synchronous while still seeing the body.
    """

    raw: bytes
    text: str
    json: Any | None

    @classmethod
    def from_bytes(cls, raw: bytes) -> "RequestPayload":
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed: Any | None = json.loads(text) if text.strip() else None
        except ValueError:
            parsed = None
        return cls(raw=raw, text=text, json=parsed)

    @classmethod
    def empty(cls) -> "RequestPayload":
        return cls.from_bytes(b"")


class RuleResult(ABC):
    """Base class for rule application results."""

    @abstractmethod
    def get_result_type(self) -> str:
        """Return the type of result."""


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
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
    ):
        self.pattern = pattern
        self.replacement = replacement
        self.method = method
        self.name = name
        # Header names are case-insensitive; normalise once so matching is a plain lookup.
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.query = dict(query or {})

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(
            pattern=data["pattern"],
            replacement=data["replacement"],
            method=data.get("method", None),
            name=data.get("name", None),
            headers=data.get("headers"),
            query=data.get("query"),
        )

    def matches(self, request: Request) -> bool:
        """Check if the rule matches the request.

        All configured predicates must hold (logical AND). Predicate values are regular
        expressions matched against the whole value.
        """
        if self.method is not None and request.method.lower() != self.method.lower():
            # if rule is limited to a specific HTTP method, validate first.
            return False

        if re.match(self.pattern, request.url.path) is None:
            return False

        if not _mapping_matches(self.headers, request.headers):
            return False

        return _mapping_matches(self.query, request.query_params)

    def apply(
        self, request: Request, payload: RequestPayload | None = None
    ) -> RuleResult:
        """Apply the rule to the request."""
        payload = payload if payload is not None else RequestPayload.empty()
        path = f"{request.url.path}"
        if request.url.fragment:
            # If a URL fragment component is present, we URL encode it and include it in the path to proxy.
            path += quote("#") + request.url.fragment

        result = self._url_for(path)

        # Check if the replacement is a file template
        if result.startswith(PROXYRULES_FILE_TEMPLATE_PREFIX):
            # Extract the file path from the file:/// URL
            file_path = result[len(PROXYRULES_FILE_TEMPLATE_PREFIX) - 1 :]

            # Create template context from request
            template_context = self._create_template_context(request, payload)

            return TemplateRuleResult(
                template_path=file_path,
                template_context=template_context,
            )
        else:
            # Regular URL replacement
            return URLRuleResult(url=result)

    def _url_for(self, path: str) -> str:
        return re.sub(self.pattern, self.replacement, path)

    def _create_template_context(
        self, request: Request, payload: RequestPayload
    ) -> dict:
        """Create template context from the request, using the same logic as templating.py."""
        path = request.url.path
        _, identifiers = parse_template_name_segments_and_identifiers(
            path, default_identifier_key="id"
        )
        return {
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "path": request.url.path,
            "method": request.method,
            "request_json": payload.json,
            **identifiers,
        }


def _mapping_matches(predicates: Mapping[str, str], actual: Mapping[str, str]) -> bool:
    """True when every predicate regex fully matches the corresponding actual value."""
    for key, pattern in predicates.items():
        value = actual.get(key)
        if value is None or re.fullmatch(pattern, value) is None:
            return False
    return True

"""Rules for the proxy rules strategy."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

from fastapi import Request

from mockstack.constants import PROXYRULES_FILE_TEMPLATE_PREFIX
from mockstack.templating import parse_template_name_segments_and_identifiers


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

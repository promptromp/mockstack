"""Rules for the proxy rules strategy."""

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Final, Self
from urllib.parse import quote

from fastapi import Request
from jinja2 import Environment, StrictUndefined, Template

from mockstack.constants import MOCKSTACK_OWNED_RESPONSE_HEADERS, PROXYRULES_FILE_TEMPLATE_PREFIX
from mockstack.templating import parse_template_name_segments_and_identifiers


JINJA_DELIMITERS = ("{{", "{%")

# Template context names owned by the strategy. They always win over path-inferred
# identifiers, and a named group in ``pattern`` may not shadow them.
RESERVED_CONTEXT_KEYS: Final = frozenset({"query", "headers", "path", "method", "request_json", "groups"})

# Sentinel returned by ``lookup_path`` for an absent path, so a present JSON ``null``
# (``None``) stays distinguishable from "not there".
MISSING: Final = object()

# ``\1``..``\9`` or ``\g<name>``: regex backreferences, which are only expanded by
# ``re.sub`` and therefore never in template mode. Only literal template text is
# scanned; the same characters inside a Jinja expression or comment are not one.
_BACKREFERENCE_RE = re.compile(r"\\[1-9]|\\g<")

# An HTTP field name is an RFC 9110 token.
_HEADER_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
# Control characters are not allowed in a field value, except horizontal tab.
_INVALID_HEADER_VALUE_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

_FIXTURE_ONLY_FIELDS_ERROR = "status and response_headers only apply to file:/// fixtures"


@dataclass(frozen=True)
class RequestPayload:
    """The request body, read exactly once by the strategy and shared with every rule.

    Keeping this separate from ``Request`` lets ``Rule.matches`` / ``Rule.apply`` stay
    synchronous while still seeing the body. ``text`` and ``json`` are decoded lazily,
    on first access, so rules without body predicates never pay for parsing.
    """

    raw: bytes

    @cached_property
    def text(self) -> str:
        return self.raw.decode("utf-8", errors="replace")

    @cached_property
    def json(self) -> Any | None:
        """Parsed JSON body, or ``None`` when empty, not JSON, or nested too deeply."""
        if not self.text.strip():
            return None
        try:
            return json.loads(self.text)
        except (ValueError, RecursionError):
            return None

    @classmethod
    def from_bytes(cls, raw: bytes) -> "RequestPayload":
        return cls(raw)

    @classmethod
    def empty(cls) -> "RequestPayload":
        return cls(b"")


def lookup_path(data: Any, dotted: str) -> Any:
    """Resolve a dotted path (``a.b.0.c``) inside parsed JSON.

    Returns ``MISSING`` when the path is absent; a present JSON ``null`` is ``None``.
    """
    current = data
    for segment in dotted.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                return MISSING
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def json_text(value: Any) -> str:
    """The text a ``json`` predicate is matched against.

    Strings are compared raw (no quotes); everything else as a compact JSON literal
    (``true``, ``null``, ``1.5``, ``{"a":1}``) with sorted keys.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


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
    """A rule for the proxy rules strategy.

    Everything that can be validated is validated here, at load time: regexes are
    compiled, predicate values coerced to strings, the fixture ``status`` and
    ``response_headers`` checked, and a Jinja replacement compiled with strict
    undefined. A bad rules file therefore fails when it is loaded rather than on the
    first request that happens to reach the broken rule.
    """

    def __init__(
        self,
        pattern: str,
        replacement: str,
        method: str | None = None,
        name: Any | None = None,
        headers: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any | None = None,
        json: Mapping[str, Any] | None = None,
        status: Any | None = None,
        response_headers: Any | None = None,
        env: Environment | None = None,
    ):
        # YAML may parse e.g. `name: 2024` as an int.
        self.name = str(name) if name is not None else None
        self.pattern = pattern
        self.replacement = replacement
        self.method = method
        self.env = env

        # Header names are case-insensitive; normalise once so matching is a plain lookup.
        self.headers = {str(k).lower(): self._predicate_value(k, v) for k, v in (headers or {}).items()}
        self.query = {str(k): self._predicate_value(k, v) for k, v in (query or {}).items()}
        self.json = {str(k): self._predicate_value(k, v) for k, v in (json or {}).items()}
        self.body = str(body) if body is not None else None

        self._method = method.lower() if method is not None else None
        self._pattern = re.compile(pattern)
        self._headers = {k: re.compile(v) for k, v in self.headers.items()}
        self._query = {k: re.compile(v) for k, v in self.query.items()}
        self._json = {k: re.compile(v) for k, v in self.json.items()}
        self._body = re.compile(self.body) if self.body is not None else None

        shadowed = sorted(RESERVED_CONTEXT_KEYS.intersection(self._pattern.groupindex))
        if shadowed:
            raise ValueError(f"rule {self.name!r}: named group {shadowed[0]!r} shadows a reserved template variable")

        # The decision to render is made on the operator-authored `replacement`, never
        # on request-controlled data.
        self._is_template = any(d in replacement for d in JINJA_DELIMITERS)

        # How a rendered fixture is answered. A plain URL replacement can never serve
        # one; a Jinja replacement is checked per request, in `apply`.
        self.status = self._status(status)
        self.response_headers = self._response_headers(response_headers)
        if self._has_fixture_only_fields and not (
            self._is_template or replacement.startswith(PROXYRULES_FILE_TEMPLATE_PREFIX)
        ):
            raise ValueError(f"rule {self.name!r}: {_FIXTURE_ONLY_FIELDS_ERROR}, and the replacement is not one")

        self._replacement_template: Template | None = None
        if env is not None and self._is_template:
            template_env = env.overlay(undefined=StrictUndefined)
            if any(
                # "data" is a Jinja lexer token type (literal template text), not a password.
                token_type == "data" and _BACKREFERENCE_RE.search(value)  # noqa: S105
                for _, token_type, value in template_env.lex(replacement)
            ):
                raise ValueError(
                    f"rule {self.name!r}: replacement mixes Jinja delimiters with a regex "
                    "backreference; backreferences are not expanded in template mode, "
                    "use {{ groups[0] }} or a named group instead"
                )
            self._replacement_template = template_env.from_string(replacement)

    def _predicate_value(self, key: Any, value: Any) -> str:
        if value is None:
            raise ValueError(f"rule {self.name!r}: predicate {str(key)!r} has no value")
        return str(value)

    def _status(self, value: Any) -> int | None:
        """The fixture status: an integer, or a string of ASCII digits, from 200 to 599."""
        if value is None:
            return None
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or not 200 <= value <= 599:
            raise ValueError(f"rule {self.name!r}: status must be an integer from 200 to 599, got {value!r}")
        return value

    def _response_headers(self, value: Any) -> tuple[tuple[str, str], ...]:
        """``(name, value)`` pairs in file order; a list value repeats the header."""
        if value is None:
            return ()
        if not isinstance(value, Mapping):
            # Every rules-file mistake is a ValueError naming the rule, whatever its kind.
            raise ValueError(  # noqa: TRY004
                f"rule {self.name!r}: response_headers must be a mapping of header name to value"
            )
        headers: list[tuple[str, str]] = []
        for key, raw in value.items():
            name = str(key)
            if _HEADER_NAME_RE.fullmatch(name) is None:
                raise ValueError(f"rule {self.name!r}: invalid response header name {name!r}")
            if name.lower() in MOCKSTACK_OWNED_RESPONSE_HEADERS:
                raise ValueError(f"rule {self.name!r}: response header {name!r} is set by mockstack")
            values = raw if isinstance(raw, list) else [raw]
            if not values or any(item is None for item in values):
                raise ValueError(f"rule {self.name!r}: response header {name!r} has no value")
            headers.extend((name, self._response_header_value(name, item)) for item in values)
        return tuple(headers)

    def _response_header_value(self, name: str, value: Any) -> str:
        """A scalar coerced to a string that Starlette can send as a single header value."""
        if isinstance(value, str | int | float):
            text = str(value)
            if _INVALID_HEADER_VALUE_RE.search(text) is None and _is_latin1(text):
                return text
        raise ValueError(f"rule {self.name!r}: invalid response header value for {name!r}")

    @property
    def _has_fixture_only_fields(self) -> bool:
        return self.status is not None or bool(self.response_headers)

    @classmethod
    def from_dict(cls, data: dict[str, Any], env: Environment | None = None) -> Self:
        return cls(
            pattern=data["pattern"],
            replacement=data["replacement"],
            method=data.get("method"),
            name=data.get("name"),
            headers=data.get("headers"),
            query=data.get("query"),
            body=data.get("body"),
            json=data.get("json"),
            status=data.get("status"),
            response_headers=data.get("response_headers"),
            env=env,
        )

    def match(self, request: Request) -> re.Match[str] | None:
        """Match ``pattern`` against the request path (``re.match`` semantics)."""
        return self._pattern.match(request.url.path)

    def matches(self, request: Request, payload: RequestPayload | None = None) -> bool:
        """Check if the rule matches the request.

        All configured predicates must hold (logical AND). ``body`` / ``json`` predicates
        never match when ``payload`` is ``None`` or empty (no request body).
        """
        if self._method is not None and request.method.lower() != self._method:
            # if rule is limited to a specific HTTP method, validate first.
            return False

        if self.match(request) is None:
            return False

        if not _mapping_matches(self._headers, request.headers):
            return False

        if not _mapping_matches(self._query, request.query_params):
            return False

        if self._body is None and not self._json:
            return True

        if payload is None or not payload.raw:
            return False

        if self._body is not None and self._body.search(payload.text) is None:
            return False

        for dotted, pattern in self._json.items():
            value = lookup_path(payload.json, dotted)
            if value is MISSING or pattern.fullmatch(json_text(value)) is None:
                return False

        return True

    def apply(self, request: Request, payload: RequestPayload | None = None) -> RuleResult:
        """Apply the rule to the request.

        A Jinja replacement is rendered directly against the template context: regex
        backreferences are not expanded and the URL fragment is not carried over. A
        plain replacement goes through ``re.sub``. Request data only ever reaches a
        template as context values, which Jinja does not re-parse as template source.
        """
        payload = payload if payload is not None else RequestPayload.empty()
        match = self.match(request)
        context: dict[str, Any] | None = None

        if self._replacement_template is not None:
            context = self._create_template_context(request, payload, match)
            result = self._replacement_template.render(**context)
        else:
            path = request.url.path
            if request.url.fragment:
                # If a URL fragment component is present, we URL encode it and include it in the path to proxy.
                path += quote("#") + request.url.fragment
            result = self._pattern.sub(self.replacement, path)

        if not result.startswith(PROXYRULES_FILE_TEMPLATE_PREFIX):
            if self._has_fixture_only_fields:
                raise ValueError(
                    f"rule {self.name!r}: {_FIXTURE_ONLY_FIELDS_ERROR}, but the replacement rendered a URL"
                )
            return URLRuleResult(url=result)

        if context is None:
            context = self._create_template_context(request, payload, match)
        # Keep the leading "/" of the absolute path after the file:// scheme.
        return TemplateRuleResult(
            template_path=result[len(PROXYRULES_FILE_TEMPLATE_PREFIX) - 1 :],
            template_context=context,
        )

    def _create_template_context(
        self,
        request: Request,
        payload: RequestPayload,
        match: re.Match[str] | None,
    ) -> dict[str, Any]:
        """Create the template context from the request.

        Precedence, lowest to highest: identifiers inferred from the path (as in
        templating.py), named groups, then the reserved keys. Named groups that did not
        participate in the match are dropped, so referencing them fails loudly under
        strict undefined instead of rendering ``None``.
        """
        path = request.url.path
        _, identifiers = parse_template_name_segments_and_identifiers(path, default_identifier_key="id")
        groups = match.groups() if match else ()
        named = {k: v for k, v in match.groupdict().items() if v is not None} if match else {}
        return {
            **identifiers,
            **named,
            "groups": groups,
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "path": path,
            "method": request.method,
            "request_json": payload.json,
        }


def _is_latin1(text: str) -> bool:
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def _mapping_matches(predicates: Mapping[str, re.Pattern[str]], actual: Mapping[str, str]) -> bool:
    """True when every predicate regex fully matches the corresponding actual value."""
    for key, pattern in predicates.items():
        value = actual.get(key)
        if value is None or pattern.fullmatch(value) is None:
            return False
    return True

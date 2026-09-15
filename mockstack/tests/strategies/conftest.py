"""Fixtures for building strategies and sending them requests."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import Request, Response

from mockstack.strategies.proxyrules import ProxyRulesStrategy


@pytest.fixture
def traced_request(make_request: Callable[..., Request], span) -> Callable[..., Request]:
    """Factory: ``make_request`` with ``request.state.span`` set, as the middleware does."""

    def _make(*args: Any, **kwargs: Any) -> Request:
        request = make_request(*args, **kwargs)
        request.state.span = span
        return request

    return _make


@pytest.fixture
def proxyrules_strategy(settings, write_rules) -> Callable[..., ProxyRulesStrategy]:
    """Factory: a ``ProxyRulesStrategy`` built from the ``settings`` fixture.

    ``rules``, when given, are written to their own rules file and loaded through the
    strategy, as at startup. ``settings_overrides`` are applied with ``model_copy``, so
    they are not validated (a test can set an invalid ``proxyrules_redirect_via``).
    """

    def _build(rules: list[dict[str, Any]] | None = None, **settings_overrides: Any) -> ProxyRulesStrategy:
        if rules is not None:
            settings_overrides["proxyrules_rules_filename"] = write_rules(rules)
        return ProxyRulesStrategy(settings.model_copy(update=settings_overrides))

    return _build


@pytest.fixture
def apply_rule(
    proxyrules_strategy: Callable[..., ProxyRulesStrategy], traced_request
) -> Callable[..., Awaitable[Response]]:
    """Factory: apply ``request`` (by default ``GET /x``) through a strategy whose rules
    file holds only ``rule``; ``settings_overrides`` go to ``proxyrules_strategy``."""

    async def _apply(rule: dict[str, Any], request: Request | None = None, **settings_overrides: Any) -> Response:
        strategy = proxyrules_strategy(rules=[rule], **settings_overrides)
        return await strategy.apply(request if request is not None else traced_request("/x"))

    return _apply


@pytest.fixture
def upstream_send():
    """Patch ``httpx.AsyncClient.send``; each test sets ``return_value`` or ``side_effect``."""
    with patch.object(httpx.AsyncClient, "send", new_callable=AsyncMock) as send:
        yield send


@pytest.fixture
def span_attributes(span) -> Callable[[], dict[str, Any]]:
    """Factory: the span's final attribute values, rebuilt from every ``set_attribute``
    call with last-write-wins semantics (as OpenTelemetry spans behave), so a test can
    assert on the value a real span would report rather than merely that some call was
    made with it."""

    def _attributes() -> dict[str, Any]:
        return {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}

    return _attributes

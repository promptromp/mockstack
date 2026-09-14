"""Fixtures for building strategies and sending them requests."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import Request, Response

from mockstack.strategies.proxyrules import ProxyRulesStrategy


@pytest.fixture
def traced_request(make_request, span) -> Callable[..., Request]:
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
def apply_rule(proxyrules_strategy, traced_request) -> Callable[..., Awaitable[Response]]:
    """Factory: apply ``request`` (by default ``GET /x``) through a strategy whose rules
    file holds only ``rule``; ``settings_overrides`` go to ``proxyrules_strategy``."""

    async def _apply(rule: dict[str, Any], request: Request | None = None, **settings_overrides: Any) -> Response:
        strategy = proxyrules_strategy(rules=[rule], **settings_overrides)
        return await strategy.apply(request if request is not None else traced_request("/x"))

    return _apply

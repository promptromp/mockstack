"""Fixtures shared by the unit tests and the live tests."""

import os
import sys
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI, Request
from starlette.types import Message

import mockstack
from mockstack.config import OpenTelemetrySettings, Settings
from mockstack.constants import ProxyRulesRedirectVia
from mockstack.strategies.filefixtures import FileFixturesStrategy


class _EnvIsolatedSettings(Settings):
    """``Settings`` that ignore environment variables and ``.env`` files entirely.

    Passing ``_env_file=None`` only skips the ``.env`` file source; the
    environment-variable source still runs and would pick up a developer's own
    exported ``MOCKSTACK__*`` variables. Overriding ``settings_customise_sources``
    to keep only ``init_settings`` means a test's ``Settings`` are built solely from
    the keyword arguments given (and field defaults), never from the shell.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings,)


@pytest.fixture(scope="session")
def make_settings() -> Callable[..., Settings]:
    """Factory: ``Settings`` that ignore ``MOCKSTACK__*`` environment variables and
    any ``.env`` file, and keep OpenTelemetry off.

    ``overrides`` are passed to ``Settings`` and take precedence, including over
    ``opentelemetry``. Session-scoped so module-scoped live servers can use it too.
    """

    def _make(**overrides: Any) -> Settings:
        options: dict[str, Any] = {
            "opentelemetry": OpenTelemetrySettings(enabled=False),
            **overrides,
        }
        return _EnvIsolatedSettings(**options)

    return _make


@pytest.fixture
def without_opentelemetry(monkeypatch):
    """Make the OpenTelemetry packages unimportable, as when the ``opentelemetry`` extra
    is not installed. ``mockstack.tracing``, which imports them, is unloaded too."""
    loaded = [name for name in sys.modules if name == "opentelemetry" or name.startswith("opentelemetry.")]
    # A module left in sys.modules would still import; None makes each import fail.
    for name in {"opentelemetry", *loaded}:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delitem(sys.modules, "mockstack.tracing", raising=False)
    monkeypatch.delattr(mockstack, "tracing", raising=False)


@pytest.fixture
def templates_dir():
    """Return the path to the test templates directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "templates")


@pytest.fixture
def proxyrules_rules_filename():
    """Return the path to the test proxyrules rules file."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "proxyrules.yml")


@pytest.fixture
def settings(make_settings, templates_dir, proxyrules_rules_filename):
    """Proxyrules settings on the shared rules file, redirecting with a 307."""
    return make_settings(
        strategy="proxyrules",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
        proxyrules_simulate_create_on_missing=False,
    )


@pytest.fixture
def settings_reverse_proxy(make_settings, templates_dir, proxyrules_rules_filename):
    """Proxyrules settings on the shared rules file, in reverse-proxy mode."""
    return make_settings(
        strategy="proxyrules",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
    )


@pytest.fixture
def settings_filefixtures(make_settings, templates_dir):
    """Filefixtures settings on the shared templates directory."""
    return make_settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
    )


@pytest.fixture
def span():
    """Create a mock span object for testing."""
    span = MagicMock()
    span.set_attribute = MagicMock()
    return span


@pytest.fixture
def app(settings, span):
    """Create a FastAPI app for testing."""
    app = FastAPI()
    app.state.strategy = FileFixturesStrategy(settings)
    app.state.span = span
    return app


@pytest_asyncio.fixture
async def asgi_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """An ``httpx.AsyncClient`` that calls the ``app`` fixture in-process.

    Requests go through ``httpx.ASGITransport``, so routes and middleware added to
    ``app`` before the first request are served. The app's lifespan does not run.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.fixture
def make_request() -> Callable[..., Request]:
    """Factory: a Starlette ``Request`` with a real ASGI ``receive`` channel.

    ``headers`` is a mapping, or a sequence of ``(name, value)`` pairs to repeat a
    header. The first ``receive()`` delivers ``body``; any later one reports a client
    disconnect. Extra keyword arguments are added to the ASGI scope (for example
    ``scheme``, ``server`` or ``client``).
    """

    def _make(
        path: str = "/",
        method: str = "GET",
        headers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        query: bytes = b"",
        body: bytes = b"",
        **scope: Any,
    ) -> Request:
        pairs = headers.items() if isinstance(headers, Mapping) else headers or ()
        messages: list[Message] = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive() -> Message:
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": query,
                "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in pairs],
                **scope,
            },
            receive=receive,
        )

    return _make


@pytest.fixture(scope="session")
def write_rules(tmp_path_factory: pytest.TempPathFactory) -> Callable[[list[dict[str, Any]]], Path]:
    """Factory: write ``rules`` as a proxyrules rules file and return its path.

    Each call writes a new ``rules.yml`` in its own temporary directory. Session-scoped
    so module-scoped live servers can use it as well as unit tests.
    """

    def _write(rules: list[dict[str, Any]]) -> Path:
        path = tmp_path_factory.mktemp("rules") / "rules.yml"
        path.write_text(yaml.safe_dump({"rules": rules}))
        return path

    return _write


@pytest.fixture
def write_template(tmp_path: Path) -> Callable[[str, str], Path]:
    """Factory: write ``content`` to ``relative_path`` under ``tmp_path``; return the path."""

    def _write(relative_path: str, content: str) -> Path:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    return _write

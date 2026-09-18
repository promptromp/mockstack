"""Unit tests for the telemetry module: tracing is optional, and so are its packages."""

import subprocess
import sys
import textwrap
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

import mockstack
from mockstack.config import OpenTelemetrySettings
from mockstack.main import create_app
from mockstack.telemetry import (
    NULL_SPAN,
    OpenTelemetryUnavailableError,
    current_span,
    opentelemetry_provider,
)


@pytest.fixture
def tracing_settings(make_settings, templates_dir):
    return make_settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        opentelemetry=OpenTelemetrySettings(enabled=True),
    )


def test_current_span_without_tracing_records_nothing(make_request):
    span = current_span(make_request("/"))

    assert span is NULL_SPAN
    span.set_attribute("key", "value")


def test_current_span_is_the_tracing_middlewares_span(make_request, span):
    request = make_request("/")
    request.state.span = span

    assert current_span(request) is span


def test_disabled_does_not_import_opentelemetry(without_opentelemetry, settings_filefixtures):
    app = FastAPI()

    opentelemetry_provider(app, settings_filefixtures)

    assert app.user_middleware == []
    assert "mockstack.tracing" not in sys.modules


def test_enabled_installs_tracing(tracing_settings):
    app = FastAPI()

    with patch("mockstack.tracing.install") as install:
        opentelemetry_provider(app, tracing_settings)

    install.assert_called_once_with(app, tracing_settings)


def test_enabled_without_the_extra_names_it(without_opentelemetry, tracing_settings):
    with pytest.raises(OpenTelemetryUnavailableError) as excinfo:
        opentelemetry_provider(FastAPI(), tracing_settings)

    assert excinfo.value.missing_module.startswith("opentelemetry")
    assert "pip install 'mockstack[opentelemetry]'" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ModuleNotFoundError)


def test_another_missing_module_keeps_its_error(monkeypatch, tracing_settings):
    """Only missing OpenTelemetry packages mean the extra is not installed."""
    monkeypatch.setitem(sys.modules, "mockstack.tracing", None)
    monkeypatch.delattr(mockstack, "tracing", raising=False)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        opentelemetry_provider(FastAPI(), tracing_settings)

    assert not isinstance(excinfo.value, OpenTelemetryUnavailableError)
    assert excinfo.value.name == "mockstack.tracing"


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["filefixtures", "proxyrules"])
async def test_app_serves_without_opentelemetry(
    without_opentelemetry, make_settings, write_template, write_rules, tmp_path, strategy
):
    """Without the extra, and with tracing off, both strategies serve and simulate
    creating resources, adding their span attributes to ``NULL_SPAN``."""
    template = write_template("api-projects.j2", '{"id": "1234"}')
    rules = write_rules([{"name": "projects", "pattern": "/api/projects/1234", "replacement": f"file:///{template}"}])
    settings = make_settings(
        strategy=strategy,
        templates_dir=tmp_path,
        proxyrules_rules_filename=rules,
        proxyrules_simulate_create_on_missing=True,
    )

    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        fetched = await client.get("/api/projects/1234")
        created = await client.post("/api/orders", json={"name": "new"})

    assert fetched.json() == {"id": "1234"}
    assert created.status_code == 201
    assert "mockstack.tracing" not in sys.modules


def test_mockstack_never_imports_opentelemetry_unless_enabled(tmp_path):
    """A fresh interpreter serves a request without importing OpenTelemetry, and
    enabling tracing without it is a configuration error, not a traceback."""
    (tmp_path / "index.j2").write_text("{}")
    script = textwrap.dedent(
        f"""
        import sys
        from importlib.abc import MetaPathFinder

        class NoOpenTelemetry(MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "opentelemetry" or name.startswith("opentelemetry."):
                    raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)

        sys.meta_path.insert(0, NoOpenTelemetry())

        import httpx
        from mockstack.main import create_app, run
        from mockstack.config import Settings

        import asyncio

        app = create_app(Settings(templates_dir={str(tmp_path)!r}))

        async def get():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return (await client.get("/")).status_code

        assert asyncio.run(get()) == 200
        assert not any(name.split(".")[0] == "opentelemetry" for name in sys.modules), "imported"
        run(["--templates-dir", {str(tmp_path)!r}, "--opentelemetry.enabled"])
        """
    )

    result = subprocess.run(  # noqa: S603 -- runs this interpreter on the script above
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=tmp_path, check=False
    )

    assert result.returncode == 2, result.stderr
    assert result.stderr == (
        "mockstack: error: --opentelemetry.enabled is on, but the OpenTelemetry packages are not installed\n"
        "  environment or .env: MOCKSTACK__OPENTELEMETRY__ENABLED\n"
        "  install them with: pip install 'mockstack[opentelemetry]'\n"
    )

"""Shared fixtures for the unit-tests."""

import os

import pytest
from fastapi import FastAPI

from mockstack.config import OpenTelemetrySettings, Settings
from mockstack.constants import ProxyRulesRedirectVia
from mockstack.strategies.filefixtures import FileFixturesStrategy


@pytest.fixture
def app(settings):
    """Create a FastAPI app for testing."""
    app = FastAPI()
    app.state.strategy = FileFixturesStrategy(settings)
    return app


@pytest.fixture
def templates_dir():
    """Return the path to the test templates directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "templates")


@pytest.fixture
def proxyrules_rules_filename():
    """Return the path to the test proxyrules rules file."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "proxyrules.yml")


@pytest.fixture
def settings(templates_dir, proxyrules_rules_filename):
    """Return a Settings object for testing."""
    return Settings(
        templates_dir=templates_dir,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )


@pytest.fixture
def settings_reverse_proxy(templates_dir, proxyrules_rules_filename):
    """Return a Settings object for testing with reverse proxy enabled."""
    return Settings(
        templates_dir=templates_dir,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )

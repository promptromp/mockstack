"""Shared fixtures for the unit-tests."""

import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from mockstack.config import OpenTelemetrySettings, Settings
from mockstack.constants import ProxyRulesRedirectVia
from mockstack.strategies.filefixtures import FileFixturesStrategy


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
        strategy="proxyrules",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
        proxyrules_simulate_create_on_missing=False,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )


@pytest.fixture
def settings_reverse_proxy(templates_dir, proxyrules_rules_filename):
    """Return a Settings object for testing with reverse proxy enabled."""
    return Settings(
        strategy="proxyrules",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
        proxyrules_rules_filename=proxyrules_rules_filename,
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )


@pytest.fixture
def settings_filefixtures(templates_dir):
    """Return a Settings object for testing with filefixtures strategy."""
    return Settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        filefixtures_enable_templates_for_post=False,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )

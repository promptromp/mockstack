"""Shared fixtures for the unit-tests."""

import os

import pytest
from fastapi import FastAPI

from mockstack.config import OpenTelemetrySettings, Settings


@pytest.fixture
def app():
    """Create a FastAPI app for testing."""
    return FastAPI()


@pytest.fixture
def templates_dir():
    """Return the path to the test templates directory."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "templates")


@pytest.fixture
def settings(templates_dir):
    """Return a Settings object for testing."""
    return Settings(
        templates_dir=templates_dir,
        opentelemetry=OpenTelemetrySettings(enabled=False),
    )

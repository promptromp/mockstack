"""Unit tests for the filefixtures strategy module."""

import os
import pytest
from fastapi import Request
from fastapi.templating import Jinja2Templates
from unittest.mock import MagicMock, patch

from mockstack.config import Settings
from mockstack.strategies.filefixtures import (
    looks_like_id,
    infer_template_arguments,
    FileFixturesStrategy,
)


@pytest.fixture
def templates_dir():
    """Return the path to the test templates directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "fixtures", "templates"
    )


@pytest.mark.parametrize(
    "chunk,expected",
    [
        ("1234", True),  # Even length numeric
        ("1234567890", True),  # Even length numeric
        ("1234567890abcdef", True),  #  even length hex
        ("1234567890abcdefg", False),  # Odd length hex
        ("3a4e5ad9-17ee-41af-972f-864dfccd4856", True),  # UUID
        ("project", False),
        ("api", False),
        ("v1", False),
    ],
)
def test_looks_like_id(chunk: str, expected: bool) -> None:
    """Test the looks_like_id function with various inputs."""
    assert looks_like_id(chunk) == expected


@pytest.mark.parametrize(
    "path,expected_name,expected_context",
    [
        ("/api/v1/projects/1234", "api-v1-projects.j2", {"projects": "1234"}),
        (
            "/api/v1/users/3a4e5ad9-17ee-41af-972f-864dfccd4856",
            "api-v1-users.j2",
            {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
        ),
        ("/api/v1/projects", "api-v1-projects.j2", {}),
    ],
)
def test_infer_template_arguments(
    path: str, expected_name: str, expected_context: dict
) -> None:
    """Test the infer_template_arguments function with various paths."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )

    result = infer_template_arguments(request)

    assert result["name"] == expected_name
    assert result["context"] == expected_context


def test_file_fixtures_strategy_init(templates_dir):
    """Test the FileFixturesStrategy initialization."""
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    assert isinstance(strategy.templates, Jinja2Templates)
    # Since we can't access the directory directly, we'll verify the strategy was initialized
    assert strategy.templates is not None


@patch("mockstack.strategies.filefixtures.Jinja2Templates")
def test_file_fixtures_strategy_apply(mock_templates, templates_dir):
    """Test the FileFixturesStrategy apply method."""
    # Setup
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    mock_template_response = MagicMock()
    mock_templates.return_value.TemplateResponse.return_value = mock_template_response

    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/1234",
            "query_string": b"",
            "headers": [],
        }
    )

    # Execute
    result = strategy.apply(request)

    # Assert
    assert result == mock_template_response
    mock_templates.return_value.TemplateResponse.assert_called_once()
    call_args = mock_templates.return_value.TemplateResponse.call_args[1]
    assert call_args["request"] == request
    assert call_args["name"] == "api-v1-projects.j2"
    assert call_args["context"] == {"projects": "1234"}

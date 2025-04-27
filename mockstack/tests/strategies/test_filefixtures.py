"""Unit tests for the filefixtures strategy module."""

import os
import pytest
from fastapi import Request, HTTPException
from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound
from unittest.mock import MagicMock, patch

from mockstack.config import Settings
from mockstack.strategies.filefixtures import (
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
    "path,expected_name,expected_context,expected_media_type",
    [
        (
            "/api/v1/projects/1234",
            "api-v1-projects.j2",
            {"projects": "1234"},
            "application/json",
        ),
        (
            "/api/v1/users/3a4e5ad9-17ee-41af-972f-864dfccd4856",
            "api-v1-users.j2",
            {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
            "application/json",
        ),
        ("/api/v1/projects", "api-v1-projects.j2", {}, "application/json"),
        (
            "/1234",
            "index.j2",
            {"id": "1234"},
            "application/json",
        ),
    ],
)
def test_infer_template_arguments(
    path: str,
    expected_name: str,
    expected_context: dict,
    expected_media_type: str,
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
    assert result["media_type"] == expected_media_type


def test_infer_template_arguments_with_custom_media_type():
    """Test that custom media type from headers is respected."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects",
            "query_string": b"",
            "headers": [(b"content-type", b"application/xml")],
        }
    )

    result = infer_template_arguments(request)
    assert result["media_type"] == "application/xml"


def test_file_fixtures_strategy_init(templates_dir):
    """Test the FileFixturesStrategy initialization."""
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    assert isinstance(strategy.env, Environment)
    assert isinstance(strategy.env.loader, FileSystemLoader)
    assert strategy.env.loader.searchpath == [templates_dir]


@patch("mockstack.strategies.filefixtures.Environment")
def test_file_fixtures_strategy_apply_success(mock_env, templates_dir):
    """Test the FileFixturesStrategy apply method when template exists."""
    # Setup
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    mock_template = MagicMock()
    mock_template.render.return_value = '{"status": "success"}'
    mock_env.return_value.get_template.return_value = mock_template

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
    response = strategy.apply(request)

    # Assert
    assert response.media_type == "application/json"
    assert response.body.decode() == '{"status": "success"}'
    mock_template.render.assert_called_once_with(projects="1234")


@patch("mockstack.strategies.filefixtures.Environment")
def test_file_fixtures_strategy_apply_template_not_found(mock_env, templates_dir):
    """Test the FileFixturesStrategy apply method when template doesn't exist."""
    # Setup
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    mock_env.return_value.get_template.side_effect = TemplateNotFound(
        "Template not found"
    )

    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/1234",
            "query_string": b"",
            "headers": [],
        }
    )

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        strategy.apply(request)

    assert exc_info.value.status_code == 404
    assert "Template not found" in str(exc_info.value.detail)

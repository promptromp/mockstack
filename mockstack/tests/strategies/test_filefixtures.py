"""Unit tests for the filefixtures strategy module."""

import os
import pytest
from fastapi import Request, HTTPException
from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound
from unittest.mock import MagicMock, patch

from mockstack.config import Settings
from mockstack.strategies.filefixtures import (
    iter_possible_template_arguments,
    parse_template_name_segments_and_context,
    iter_possible_template_filenames,
    FileFixturesStrategy,
)


@pytest.fixture
def templates_dir():
    """Return the path to the test templates directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "fixtures", "templates"
    )


@pytest.mark.parametrize(
    "path,expected_results",
    [
        (
            "/api/v1/projects/1234",
            [
                {
                    "name": "api-v1-projects.j2",
                    "context": {"projects": "1234"},
                    "media_type": "application/json",
                }
            ],
        ),
        (
            "/api/v1/users/3a4e5ad9-17ee-41af-972f-864dfccd4856",
            [
                {
                    "name": "api-v1-users.j2",
                    "context": {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
                    "media_type": "application/json",
                }
            ],
        ),
        (
            "/api/v1/projects",
            [
                {
                    "name": "api-v1-projects.j2",
                    "context": {},
                    "media_type": "application/json",
                }
            ],
        ),
        (
            "/1234",
            [
                {
                    "name": "index.j2",
                    "context": {"id": "1234"},
                    "media_type": "application/json",
                }
            ],
        ),
    ],
)
def test_iter_possible_template_arguments(
    path: str,
    expected_results: list,
) -> None:
    """Test the iter_possible_template_arguments function with various paths."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )

    results = list(iter_possible_template_arguments(request))
    assert len(results) == len(expected_results)

    for actual, expected in zip(results, expected_results):
        assert actual["name"] == expected["name"]
        assert actual["context"] == expected["context"]
        assert actual["media_type"] == expected["media_type"]


def test_iter_possible_template_arguments_with_custom_media_type():
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

    results = list(iter_possible_template_arguments(request))
    assert len(results) == 1
    assert results[0]["media_type"] == "application/xml"


def test_parse_template_name_segments_and_context():
    """Test the parse_template_name_segments_and_context function."""
    # Test with a simple path
    name_segments, context = parse_template_name_segments_and_context(
        "/api/v1/projects/1234", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects"]
    assert context == {"projects": "1234"}

    # Test with a path with no identifiers
    name_segments, context = parse_template_name_segments_and_context(
        "/api/v1/projects", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects"]
    assert context == {}

    # Test with a path with only an identifier
    name_segments, context = parse_template_name_segments_and_context(
        "/1234", default_identifier_key="id"
    )
    assert name_segments == []
    assert context == {"id": "1234"}

    # Test with a path with multiple identifiers
    name_segments, context = parse_template_name_segments_and_context(
        "/api/v1/projects/1234/tasks/5678", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects", "tasks"]
    assert context == {"projects": "1234", "tasks": "5678"}


def test_iter_possible_template_filenames():
    """Test the iter_possible_template_filenames function."""
    # Test with name segments
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["api-v1-projects.j2"]

    # Test with no name segments
    filenames = list(
        iter_possible_template_filenames(
            [],
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["index.j2"]

    # Test with custom separator and extension
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            template_file_separator="_",
            template_file_extension=".html",
            default_template_name="default.html",
        )
    )
    assert filenames == ["api_v1_projects.html"]


def test_file_fixtures_strategy_init(templates_dir):
    """Test the FileFixturesStrategy initialization."""
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    assert isinstance(strategy.env, Environment)
    assert isinstance(strategy.env.loader, FileSystemLoader)
    assert strategy.env.loader.searchpath == [templates_dir]


@patch("mockstack.strategies.filefixtures.Environment")
@patch("os.path.exists")
def test_file_fixtures_strategy_apply_success(mock_exists, mock_env, templates_dir):
    """Test the FileFixturesStrategy apply method when template exists."""
    # Setup
    settings = Settings(templates_dir=templates_dir)
    strategy = FileFixturesStrategy(settings)

    mock_template = MagicMock()
    mock_template.render.return_value = '{"status": "success"}'
    mock_env.return_value.get_template.return_value = mock_template

    # Mock os.path.exists to return True for the template file
    mock_exists.return_value = True

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

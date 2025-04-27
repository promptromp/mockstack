"""Unit tests for the filefixtures strategy module."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from mockstack.strategies.filefixtures import (
    FileFixturesStrategy,
)
from mockstack.templating import (
    iter_possible_template_arguments,
    iter_possible_template_filenames,
    parse_template_name_segments_and_context,
)


@pytest.mark.parametrize(
    "path,expected_results",
    [
        (
            "/api/v1/projects/1234",
            [
                {
                    "name": "api-v1-projects.1234.j2",
                    "context": {"projects": "1234"},
                    "media_type": "application/json",
                },
                {
                    "name": "api-v1-projects.j2",
                    "context": {"projects": "1234"},
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {"projects": "1234"},
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/api/v1/users/3a4e5ad9-17ee-41af-972f-864dfccd4856",
            [
                {
                    "name": "api-v1-users.3a4e5ad9-17ee-41af-972f-864dfccd4856.j2",
                    "context": {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
                    "media_type": "application/json",
                },
                {
                    "name": "api-v1-users.j2",
                    "context": {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {"users": "3a4e5ad9-17ee-41af-972f-864dfccd4856"},
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/api/v1/projects",
            [
                {
                    "name": "api-v1-projects.j2",
                    "context": {},
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {},
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/1234",
            [
                {
                    "name": "index.j2",
                    "context": {"id": "1234"},
                    "media_type": "application/json",
                },
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
    assert len(results) == 2
    assert results[0]["media_type"] == "application/xml"
    assert results[1]["media_type"] == "application/xml"


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
    # Test with name segments and context
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            context={"projects": "1234"},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["api-v1-projects.1234.j2", "api-v1-projects.j2", "index.j2"]

    # Test with name segments and no context
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            context={},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["api-v1-projects.j2", "index.j2"]

    # Test with no name segments and context
    filenames = list(
        iter_possible_template_filenames(
            [],
            context={"id": "1234"},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["index.j2"]

    # Test with no name segments and no context
    filenames = list(
        iter_possible_template_filenames(
            [],
            context={},
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
            context={"projects": "1234"},
            template_file_separator="_",
            template_file_extension=".html",
            default_template_name="default.html",
        )
    )
    assert filenames == [
        "api_v1_projects.1234.html",
        "api_v1_projects.html",
        "default.html",
    ]


def test_filefixtures_strategy_init(settings):
    """Test the FileFixturesStrategy initialization."""
    strategy = FileFixturesStrategy(settings)
    assert strategy.templates_dir == settings.templates_dir
    assert strategy.env is not None


@pytest.mark.asyncio
async def test_filefixtures_strategy_apply(settings):
    """Test the FileFixturesStrategy apply method."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/1234",
            "query_string": b"",
            "headers": [],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await strategy.apply(request)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_success(settings):
    """Test the FileFixturesStrategy apply method when template exists."""
    # Setup
    strategy = FileFixturesStrategy(settings)

    # Create a mock template
    mock_template = MagicMock()
    mock_template.render.return_value = '{"status": "success"}'

    # Patch the environment to return our mock template
    with (
        patch.object(strategy.env, "get_template", return_value=mock_template),
        patch("os.path.exists", return_value=True),
    ):
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
        response = await strategy.apply(request)

        # Assert
        assert response.media_type == "application/json"
        assert response.body.decode() == '{"status": "success"}'
        mock_template.render.assert_called_once()


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_template_not_found(settings):
    """Test the FileFixturesStrategy apply method when template doesn't exist."""
    # Setup
    strategy = FileFixturesStrategy(settings)

    # Mock os.path.exists to return False for all template files
    with patch("os.path.exists", return_value=False):
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
            await strategy.apply(request)

        assert exc_info.value.status_code == 404
        assert "Template not found" in str(exc_info.value.detail)

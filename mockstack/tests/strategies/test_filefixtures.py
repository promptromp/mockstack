"""Unit tests for the filefixtures strategy module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request, status
import json

from mockstack.strategies.filefixtures import FileFixturesStrategy


def test_filefixtures_strategy_init(settings):
    """Test the FileFixturesStrategy initialization."""
    strategy = FileFixturesStrategy(settings)
    assert strategy.templates_dir == settings.templates_dir
    assert strategy.env is not None


def test_filefixtures_strategy_init_missing_templates_dir():
    """Test FileFixturesStrategy initialization with missing templates_dir."""
    settings = MagicMock()
    settings.templates_dir = None
    with pytest.raises(ValueError, match="templates_dir is not set"):
        FileFixturesStrategy(settings)


def test_filefixtures_strategy_str(settings):
    """Test string representation of FileFixturesStrategy."""
    strategy = FileFixturesStrategy(settings)
    assert str(settings.templates_dir) in str(strategy)


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_success(settings, span):
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
        request.state.span = span

        # Execute
        response = await strategy.apply(request)

        # Assert
        assert response.media_type == "application/json"
        assert response.body.decode() == '{"status": "success"}'
        mock_template.render.assert_called_once()


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_template_not_found(settings, span):
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
        request.state.span = span

        # Execute
        response = await strategy.apply(request)

        # Assert
        assert response.status_code == 404
        assert response.media_type == "application/json"
        assert json.loads(response.body.decode()) == settings.missing_resource_fields


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_unsupported_method(settings, span):
    """Test FileFixturesStrategy with unsupported HTTP method."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "OPTIONS",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    with pytest.raises(HTTPException) as exc_info:
        await strategy.apply(request)

    assert exc_info.value.status_code == 405
    assert exc_info.value.detail == "Method not allowed"


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_search(settings, span):
    """Test POST request that looks like a search."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/v1/projects/search",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
    )
    request.state.span = span
    request.json = AsyncMock(return_value={"query": "test"})

    mock_template = MagicMock()
    mock_template.render.return_value = '{"results": []}'

    with (
        patch.object(strategy.env, "get_template", return_value=mock_template),
        patch("os.path.exists", return_value=True),
    ):
        response = await strategy.apply(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.body.decode() == '{"results": []}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_command(settings, span):
    """Test POST request that looks like a command."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/v1/projects/123/run",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
    )
    request.state.span = span
    request.json = AsyncMock(return_value={"action": "start"})

    mock_template = MagicMock()
    mock_template.render.return_value = '{"status": "started"}'

    with (
        patch.object(strategy.env, "get_template", return_value=mock_template),
        patch("os.path.exists", return_value=True),
    ):
        response = await strategy.apply(request)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.body.decode() == '{"status": "started"}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_create(settings, span):
    """Test POST request for resource creation."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/v1/projects",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
    )
    request.state.span = span
    request.json = AsyncMock(return_value={"name": "test project"})

    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.asyncio
async def test_file_fixtures_strategy_patch(settings, span):
    """Test PATCH request."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_file_fixtures_strategy_put(settings, span):
    """Test PUT request."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "PUT",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_file_fixtures_strategy_delete(settings, span):
    """Test DELETE request."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "DELETE",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_204_NO_CONTENT


def test_file_fixtures_strategy_update_opentelemetry(settings, span):
    """Test OpenTelemetry span updates."""
    strategy = FileFixturesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    template_args = {
        "name": "test-template.j2",
        "context": {},
        "media_type": "application/json",
    }

    strategy.update_opentelemetry(request, template_args)

    span.set_attribute.assert_called_once_with(
        "mockstack.filefixtures.template_name", "test-template.j2"
    )

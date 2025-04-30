"""Unit tests for the filefixtures strategy module."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from mockstack.strategies.filefixtures import (
    FileFixturesStrategy,
)


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

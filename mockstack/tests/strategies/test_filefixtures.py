"""Unit tests for the filefixtures strategy module."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

from mockstack.strategies.filefixtures import FileFixturesStrategy


@pytest.fixture
def strategy(settings_filefixtures, tmp_path):
    """A filefixtures strategy whose templates directory is ``tmp_path``, where
    ``write_template`` writes."""
    return FileFixturesStrategy(
        settings_filefixtures.model_copy(update={"templates_dir": tmp_path})
    )


def test_filefixtures_strategy_init(settings_filefixtures):
    """Test the FileFixturesStrategy initialization."""
    strategy = FileFixturesStrategy(settings_filefixtures)
    assert strategy.templates_dir == settings_filefixtures.templates_dir
    assert strategy.env is not None


def test_filefixtures_strategy_init_missing_templates_dir():
    """Test FileFixturesStrategy initialization with missing templates_dir."""
    settings = MagicMock()
    settings.templates_dir = None
    with pytest.raises(ValueError, match="templates_dir is not set"):
        FileFixturesStrategy(settings)


def test_filefixtures_strategy_str(settings_filefixtures):
    """Test string representation of FileFixturesStrategy."""
    strategy = FileFixturesStrategy(settings_filefixtures)
    assert str(settings_filefixtures.templates_dir) in str(strategy)


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_success(
    strategy, traced_request, write_template
):
    """A GET renders the most specific template for its path."""
    write_template(
        "api-v1-projects.1234.j2", '{"status": "success", "id": "{{ projects }}"}'
    )

    response = await strategy.apply(traced_request("/api/v1/projects/1234"))

    assert response.status_code == status.HTTP_200_OK
    assert response.media_type == "application/json"
    assert response.body.decode() == '{"status": "success", "id": "1234"}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_template_not_found(
    strategy, settings_filefixtures, traced_request
):
    """Test the FileFixturesStrategy apply method when template doesn't exist."""
    response = await strategy.apply(traced_request("/api/v1/projects/1234"))

    assert response.status_code == 404
    assert response.media_type == "application/json"
    assert (
        json.loads(response.body.decode())
        == settings_filefixtures.missing_resource_fields
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_file_fixtures_strategy_apply_rejects_head_and_options(
    strategy, traced_request, method
):
    """The catch-all router routes HEAD and OPTIONS to the strategy; filefixtures keeps
    answering anything but GET/POST/PATCH/PUT/DELETE with a 405."""
    with pytest.raises(HTTPException) as info:
        await strategy.apply(traced_request("/api/v1/projects/123", method=method))
    assert info.value.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert info.value.detail == "Method not allowed"


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_search(
    strategy, traced_request, write_template
):
    """Test POST request that looks like a search."""
    write_template("api-v1-projects-search.j2", '{"results": []}')
    request = traced_request(
        "/api/v1/projects/search",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"query": "test"}',
    )

    response = await strategy.apply(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.body.decode() == '{"results": []}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_command(
    strategy, traced_request, write_template
):
    """Test POST request that looks like a command."""
    write_template("api-v1-projects-123-run.j2", '{"status": "started"}')
    request = traced_request(
        "/api/v1/projects/123/run",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"action": "start"}',
    )

    response = await strategy.apply(request)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.body.decode() == '{"status": "started"}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_create(strategy, traced_request):
    """Test POST request for resource creation."""
    request = traced_request(
        "/api/v1/projects",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"name": "test project"}',
    )

    response = await strategy.apply(request)

    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
async def test_file_fixtures_strategy_patch_put_delete(
    strategy, traced_request, method
):
    """PATCH, PUT and DELETE are acknowledged with a 204 and no body."""
    response = await strategy.apply(
        traced_request("/api/v1/projects/123", method=method)
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT


def test_file_fixtures_strategy_update_opentelemetry(strategy, traced_request, span):
    """Test OpenTelemetry span updates."""
    template_args = {
        "name": "test-template.j2",
        "context": {},
        "media_type": "application/json",
    }

    strategy.update_opentelemetry(traced_request("/test"), template_args)

    span.set_attribute.assert_called_once_with(
        "mockstack.filefixtures.template_name", "test-template.j2"
    )

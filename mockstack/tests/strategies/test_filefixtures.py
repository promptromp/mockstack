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
    return FileFixturesStrategy(settings_filefixtures.model_copy(update={"templates_dir": tmp_path}))


@pytest.fixture
def strategy_templates_for_post(settings_filefixtures, tmp_path):
    """Like ``strategy``, but with ``filefixtures_enable_templates_for_post`` on."""
    return FileFixturesStrategy(
        settings_filefixtures.model_copy(
            update={
                "templates_dir": tmp_path,
                "filefixtures_enable_templates_for_post": True,
            }
        )
    )


@pytest.fixture
def strategy_no_simulate_create(settings_filefixtures, tmp_path):
    """Like ``strategy``, but with ``filefixtures_simulate_create_on_missing`` off."""
    return FileFixturesStrategy(
        settings_filefixtures.model_copy(
            update={
                "templates_dir": tmp_path,
                "filefixtures_simulate_create_on_missing": False,
            }
        )
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
async def test_file_fixtures_strategy_apply_success(strategy, traced_request, write_template):
    """A GET renders the most specific template for its path."""
    write_template("api-v1-projects.1234.j2", '{"status": "success", "id": "{{ projects }}"}')

    response = await strategy.apply(traced_request("/api/v1/projects/1234"))

    assert response.status_code == status.HTTP_200_OK
    assert response.media_type == "application/json"
    assert response.body.decode() == '{"status": "success", "id": "1234"}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_apply_template_not_found(strategy, settings_filefixtures, traced_request):
    """Test the FileFixturesStrategy apply method when template doesn't exist."""
    response = await strategy.apply(traced_request("/api/v1/projects/1234"))

    assert response.status_code == 404
    assert response.media_type == "application/json"
    assert json.loads(response.body.decode()) == settings_filefixtures.missing_resource_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_file_fixtures_strategy_apply_rejects_head_and_options(strategy, traced_request, method):
    """The catch-all router routes HEAD and OPTIONS to the strategy; filefixtures keeps
    answering anything but GET/POST/PATCH/PUT/DELETE with a 405."""
    with pytest.raises(HTTPException) as info:
        await strategy.apply(traced_request("/api/v1/projects/123", method=method))
    assert info.value.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert info.value.detail == "Method not allowed"


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_search(strategy, traced_request, write_template):
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
async def test_file_fixtures_strategy_post_command(strategy, traced_request, write_template):
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
@pytest.mark.parametrize(
    ("enable_templates_for_post", "simulate_create_on_missing", "template_exists", "expected_status"),
    [
        # enable_templates_for_post off: template existence is irrelevant, only
        # simulate_create_on_missing decides between a simulated create and a 404.
        (False, True, False, status.HTTP_201_CREATED),
        (False, False, False, status.HTTP_404_NOT_FOUND),
        # enable_templates_for_post on, no matching template: falls back to the same
        # simulate_create_on_missing decision as above.
        (True, True, False, status.HTTP_201_CREATED),
        (True, False, False, status.HTTP_404_NOT_FOUND),
        # enable_templates_for_post on, matching template: the template wins
        # regardless of simulate_create_on_missing.
        (True, True, True, status.HTTP_200_OK),
        (True, False, True, status.HTTP_200_OK),
    ],
)
async def test_file_fixtures_strategy_post_create_matrix(
    settings_filefixtures,
    tmp_path,
    traced_request,
    write_template,
    enable_templates_for_post,
    simulate_create_on_missing,
    template_exists,
    expected_status,
):
    """Matrix of a create-looking POST's outcome across enable_templates_for_post,
    simulate_create_on_missing and whether a matching template exists."""
    if template_exists:
        write_template("api-v1-projects.j2", '{"status": "existing template"}')
    strategy = FileFixturesStrategy(
        settings_filefixtures.model_copy(
            update={
                "templates_dir": tmp_path,
                "filefixtures_enable_templates_for_post": enable_templates_for_post,
                "filefixtures_simulate_create_on_missing": simulate_create_on_missing,
            }
        )
    )
    request = traced_request(
        "/api/v1/projects",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"name": "test project"}',
    )

    response = await strategy.apply(request)

    assert response.status_code == expected_status
    # `Response.body` is typed `bytes | memoryview`; normalize before decoding.
    body_text = bytes(response.body).decode()
    match expected_status:
        case status.HTTP_200_OK:
            assert body_text == '{"status": "existing template"}'
        case status.HTTP_201_CREATED:
            body = json.loads(body_text)
            assert body["name"] == "test project"
            assert "id" in body
            assert "createdAt" in body
        case status.HTTP_404_NOT_FOUND:
            assert json.loads(body_text) == settings_filefixtures.missing_resource_fields


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_search_simulate_create_disabled(
    strategy_no_simulate_create, traced_request, write_template
):
    """Search-like POSTs are unaffected by ``filefixtures_simulate_create_on_missing``:
    with a matching template, the template is still rendered."""
    write_template("api-v1-projects-search.j2", '{"results": []}')
    request = traced_request(
        "/api/v1/projects/search",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"query": "test"}',
    )

    response = await strategy_no_simulate_create.apply(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.body.decode() == '{"results": []}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_command_simulate_create_disabled(
    strategy_no_simulate_create, traced_request, write_template
):
    """Command-like POSTs are unaffected by ``filefixtures_simulate_create_on_missing``:
    with a matching template, the template is still rendered with a 201."""
    write_template("api-v1-projects-123-run.j2", '{"status": "started"}')
    request = traced_request(
        "/api/v1/projects/123/run",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"action": "start"}',
    )

    response = await strategy_no_simulate_create.apply(request)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.body.decode() == '{"status": "started"}'


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_search_templates_for_post_no_template(
    strategy_templates_for_post, settings_filefixtures, traced_request
):
    """Pin today's behavior: a search-like POST with templates-for-POST enabled and
    no matching template still returns 404, not a created resource."""
    request = traced_request(
        "/api/v1/projects/search",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"query": "test"}',
    )

    response = await strategy_templates_for_post.apply(request)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert json.loads(response.body.decode()) == settings_filefixtures.missing_resource_fields


@pytest.mark.asyncio
async def test_file_fixtures_strategy_post_command_templates_for_post_no_template(
    strategy_templates_for_post, settings_filefixtures, traced_request
):
    """Pin today's behavior: a command-like POST with templates-for-POST enabled and
    no matching template still returns 404, not a created resource."""
    request = traced_request(
        "/api/v1/projects/123/run",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"action": "start"}',
    )

    response = await strategy_templates_for_post.apply(request)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert json.loads(response.body.decode()) == settings_filefixtures.missing_resource_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
async def test_file_fixtures_strategy_patch_put_delete(strategy, traced_request, method):
    """PATCH, PUT and DELETE are acknowledged with a 204 and no body."""
    response = await strategy.apply(traced_request("/api/v1/projects/123", method=method))
    assert response.status_code == status.HTTP_204_NO_CONTENT


def test_file_fixtures_strategy_update_opentelemetry(strategy, traced_request, span):
    """Test OpenTelemetry span updates."""
    template_args = {
        "name": "test-template.j2",
        "context": {},
        "media_type": "application/json",
    }

    strategy.update_opentelemetry(traced_request("/test"), template_args)

    span.set_attribute.assert_called_once_with("mockstack.filefixtures.template_name", "test-template.j2")

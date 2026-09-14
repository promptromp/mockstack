"""Unit tests for the create mixin module."""

import json
from datetime import UTC, datetime

import pytest
from fastapi import status
from jinja2 import Environment

from mockstack.strategies.create_mixin import CreateMixin


class TestStrategy(CreateMixin):
    """A test strategy that uses the CreateMixin."""


@pytest.fixture
def strategy():
    """Return a test strategy instance."""
    return TestStrategy()


@pytest.fixture
def env():
    """Return a Jinja2 Environment instance."""
    return Environment()


@pytest.fixture
def created_resource_metadata():
    """Return test metadata for created resources."""
    return {
        "id": "{{ uuid4() }}",
        "createdAt": "{{ utcnow().isoformat() }}",
        "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
        "status": {"code": "OK", "error_code": None},
    }


@pytest.mark.asyncio
async def test_create_with_json_request(
    strategy, env, created_resource_metadata, traced_request
):
    """Test creating a resource with a JSON request."""
    request = traced_request(
        "/test",
        method="POST",
        headers={"content-type": "application/json", "x-user-id": "test-user"},
        body=b'{"name": "test resource"}',
    )

    response = await strategy._create(
        request,
        env=env,
        created_resource_metadata=created_resource_metadata,
    )

    assert response.status_code == status.HTTP_201_CREATED
    content = json.loads(response.body)
    assert content["name"] == "test resource"
    assert "id" in content
    assert "createdAt" in content
    assert content["createdBy"] == "test-user"
    assert content["status"]["code"] == "OK"


@pytest.mark.asyncio
async def test_create_with_non_json_request(
    strategy, env, created_resource_metadata, traced_request
):
    """Test creating a resource with a non-JSON request."""
    request = traced_request(
        "/test", method="POST", headers={"content-type": "text/plain"}
    )

    response = await strategy._create(
        request,
        env=env,
        created_resource_metadata=created_resource_metadata,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.body == b""  # FastAPI Response with no content returns empty bytes


def test_content_with_string_metadata(strategy, env, traced_request):
    """Test content generation with string metadata."""
    request = traced_request("/test", method="POST", headers={"x-user-id": "test-user"})

    resource = {"name": "test"}
    metadata = {
        "id": "{{ uuid4() }}",
        "createdBy": "{{ request.headers.get('X-User-Id') }}",
    }

    result = strategy._content(
        resource,
        env=env,
        request=request,
        created_resource_metadata=metadata,
    )

    assert result["name"] == "test"
    assert "id" in result
    assert result["createdBy"] == "test-user"


def test_content_with_dict_metadata(strategy, env, traced_request):
    """Test content generation with dictionary metadata."""
    resource = {"name": "test"}
    metadata = {
        "status": {"code": "OK", "message": None},
    }

    result = strategy._content(
        resource,
        env=env,
        request=traced_request("/test", method="POST"),
        created_resource_metadata=metadata,
    )

    assert result["name"] == "test"
    assert result["status"] == {"code": "OK", "message": None}


def test_metadata_context(strategy, traced_request):
    """Test metadata context generation."""
    request = traced_request("/test", method="POST")

    context = strategy._metadata_context(request)

    assert callable(context["utcnow"])
    assert isinstance(context["utcnow"](), datetime)
    assert context["utcnow"]().tzinfo == UTC

    assert callable(context["uuid4"])
    assert len(str(context["uuid4"]())) > 0

    assert context["request"] == request


def test_create_mixin_update_opentelemetry(strategy, traced_request, span):
    """Test OpenTelemetry span updates."""
    metadata = {"id": "test-id", "status": "active"}
    strategy._create_mixin_update_opentelemetry(
        traced_request("/test", method="POST"), metadata
    )

    span.set_attribute.assert_called_once_with(
        "mockstack.create_mixin.created_resource_metadata",
        json.dumps(metadata),
    )

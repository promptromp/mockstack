"""Unit tests for the create mixin module."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import json

import pytest
from fastapi import Request, status
from jinja2 import Environment

from mockstack.strategies.create_mixin import CreateMixin


class TestStrategy(CreateMixin):
    """A test strategy that uses the CreateMixin."""

    pass


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
async def test_create_with_json_request(strategy, env, created_resource_metadata, span):
    """Test creating a resource with a JSON request."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-user-id", b"test-user"),
            ],
        }
    )
    request.state.span = span
    request.json = AsyncMock(return_value={"name": "test resource"})

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
    strategy, env, created_resource_metadata, span
):
    """Test creating a resource with a non-JSON request."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    request.state.span = span

    response = await strategy._create(
        request,
        env=env,
        created_resource_metadata=created_resource_metadata,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.body == b""  # FastAPI Response with no content returns empty bytes


def test_content_with_string_metadata(strategy, env, span):
    """Test content generation with string metadata."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"x-user-id", b"test-user")],
        }
    )
    request.state.span = span

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


def test_content_with_dict_metadata(strategy, env, span):
    """Test content generation with dictionary metadata."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [],
        }
    )
    request.state.span = span

    resource = {"name": "test"}
    metadata = {
        "status": {"code": "OK", "message": None},
    }

    result = strategy._content(
        resource,
        env=env,
        request=request,
        created_resource_metadata=metadata,
    )

    assert result["name"] == "test"
    assert result["status"] == {"code": "OK", "message": None}


def test_metadata_context(strategy, span):
    """Test metadata context generation."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [],
        }
    )
    request.state.span = span

    context = strategy._metadata_context(request)

    assert callable(context["utcnow"])
    assert isinstance(context["utcnow"](), datetime)
    assert context["utcnow"]().tzinfo == timezone.utc

    assert callable(context["uuid4"])
    assert len(str(context["uuid4"]())) > 0

    assert context["request"] == request


def test_create_mixin_update_opentelemetry(strategy, span):
    """Test OpenTelemetry span updates."""
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [],
        }
    )
    request.state.span = span

    metadata = {"id": "test-id", "status": "active"}
    strategy._create_mixin_update_opentelemetry(request, metadata)

    span.set_attribute.assert_called_once_with(
        "mockstack.create_mixin.created_resource_metadata",
        json.dumps(metadata),
    )

"""Create mixin class."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jinja2 import Environment

from mockstack.intent import wants_json


class CreateMixin:
    """A mixin for strategies that need to simulate creation of resources."""

    async def _create(
        self, request: Request, *, env: Environment, created_resource_metadata: dict
    ) -> Response:
        if wants_json(request):
            # We return a 201 CREATED response with the resource as the body,
            # potentially injecting the resource ID into the response.
            resource = await request.json()

            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content=self._content(
                    resource,
                    request=request,
                    env=env,
                    created_resource_metadata=created_resource_metadata,
                ),
            )
        else:
            # We return a 201 CREATED response with an empty body.
            return Response(
                status_code=status.HTTP_201_CREATED,
                content=None,
            )

    def _content(
        self,
        resource: dict,
        *,
        env: Environment,
        request: Request,
        created_resource_metadata: dict,
    ) -> dict:
        """Create a new resource given a request resource.

        We use the request resource as the basis for the new resource.
        We then inject an identifier into the resource if it doesn't already have one,
        as well as any other metadata fields that are configured for the strategy.

        """

        def with_metadata(resource: dict, copy=True) -> dict:
            """Inject metadata fields into the resource."""
            _resource = resource.copy() if copy else resource
            for key, value in created_resource_metadata.items():
                if isinstance(value, str):
                    _resource[key] = env.from_string(value).render(
                        self._metadata_context(request)
                    )
                else:
                    _resource[key] = value
            return _resource

        return with_metadata(resource)

    def _metadata_context(self, request: Request) -> dict:
        """Context for injecting metadata fields into resources.

        Some care is needed to ensure that we only expose the minimum amount
        of information here since templates are user-defined.

        """
        return {
            "utcnow": lambda: datetime.now(timezone.utc),
            "uuid4": uuid4,
            "request": request,
        }

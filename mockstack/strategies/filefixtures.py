"""MockStack strategy for using file-based fixtures."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from jinja2 import Environment, FileSystemLoader

from mockstack.config import Settings
from mockstack.display import ANSIColors
from mockstack.strategies.base import BaseStrategy
from mockstack.templating import (
    iter_possible_template_arguments,
    missing_template_detail,
)


def is_json_media_type(media_type: str) -> bool:
    """Check if the media type is JSON."""
    return media_type in ("application/json", "text/json")


def looks_like_a_search(request: Request) -> bool:
    """Check if the request looks like a search.

    This is a heuristic to try and identify cases where a POST
    request is used for issuing a search rather than for creating
    a new resource.

    """
    return any(
        (
            request.url.path.endswith("_search"),
            request.url.path.endswith("/search"),
            request.url.path.endswith("_query"),
        )
    )


def looks_like_a_command(request: Request) -> bool:
    """Check if the request looks like a command.

    This is a heuristic to try and identify cases where a POST
    request is used for issuing a command rather than for creating
    a new resource.
    """
    return any(
        (
            request.url.path.endswith("_command"),
            request.url.path.endswith("/command"),
            request.url.path.endswith("_request"),
            request.url.path.endswith("/request"),
            request.url.path.endswith("_run"),
            request.url.path.endswith("/run"),
            request.url.path.endswith("_execute"),
            request.url.path.endswith("/execute"),
        )
    )


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    logger = logging.getLogger("FileFixturesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)

        if settings.templates_dir is None:
            raise ValueError("templates_dir is not set")

        self.templates_dir = Path(settings.templates_dir)
        self.created_resource_metadata = settings.created_resource_metadata
        self.missing_resource_fields = settings.missing_resource_fields

        self.env = Environment(loader=FileSystemLoader(self.templates_dir))

    def __str__(self) -> str:
        HIGHLIGHT = ANSIColors.HEADER
        ENDC = ANSIColors.ENDC

        return (
            f"{HIGHLIGHT}[filefixtures]{ENDC} "
            f"templates_dir: {HIGHLIGHT}{self.templates_dir}{ENDC}. "
        )

    async def apply(self, request: Request) -> Response:
        match request.method:
            case "GET":
                return await self._get(request)
            case "POST":
                return await self._post(request)
            case "PATCH":
                return await self._patch(request)
            case "PUT":
                return await self._put(request)
            case "DELETE":
                return await self._delete(request)
            case _:
                raise HTTPException(status_code=405, detail="Method not allowed")

    async def _post(self, request: Request) -> Response:
        """Apply the strategy for POST requests.

        POST requests are typically used for a few different purposes:

        - Creating a new resource
        - Searching for resources with a complex query that cannot be expressed in a URI
        - Executing a 'command' of some sort, like a workflow or a batch job

        We try to infer the intent from the request URI and body.
        We also allow a configuration to specify a default intent.

        """
        if looks_like_a_search(request):
            # Searching for resources with a complex query that cannot be expressed in a URI.
            return self._response_from_template(request)
        elif looks_like_a_command(request):
            # Executing a 'command' of some sort, like a workflow or a batch job.
            # We return a 201 CREATED status code with response from template.
            return self._response_from_template(
                request, status_code=status.HTTP_201_CREATED
            )
        else:
            # Creating a new resource.
            media_type = request.headers.get("Content-Type", "application/json")

            if is_json_media_type(media_type):
                # We return a 201 CREATED response with the resource as the body,
                # potentially injecting the resource ID into the response.
                resource = await request.json()

                return JSONResponse(
                    status_code=status.HTTP_201_CREATED,
                    content=self._created(resource, request=request),
                )
            else:
                # We return a 201 CREATEDresponse with an empty body.
                return Response(
                    status_code=status.HTTP_201_CREATED,
                    content=None,
                )

    async def _get(self, request: Request) -> Response:
        """Apply the strategy for GET requests.

        We try to find a template that matches the request.

        for a URI path like `/api/v1/projects/1234`, we try the following templates:

        - api-v1-projects.1234.j2
        - api-v1-projects.j2
        - index.j2

        where `1234` is the identifier of the project.

        If we find one, we render it and return the response.
        If we don't find one, we raise a 404 error.

        """
        return self._response_from_template(request)

    async def _delete(self, request: Request) -> Response:
        """Apply the strategy for DELETE requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _patch(self, request: Request) -> Response:
        """Apply the strategy for PATCH requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _put(self, request: Request) -> Response:
        """Apply the strategy for PUT requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _created(self, resource: dict, *, request: Request) -> dict:
        """Create a new resource given a request resource.

        We use the request resource as the basis for the new resource.
        We then inject an identifier into the resource if it doesn't already have one,
        as well as any other metadata fields that are configured for the strategy.

        """

        def with_metadata(resource: dict, copy=True) -> dict:
            """Inject metadata fields into the resource."""
            _resource = resource.copy() if copy else resource
            for key, value in self.created_resource_metadata.items():
                if isinstance(value, str):
                    _resource[key] = self.env.from_string(value).render(
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

    def _response_from_template(
        self, request: Request, status_code: int = status.HTTP_200_OK
    ) -> Response:
        for template_args in iter_possible_template_arguments(request):
            filename = self.templates_dir / template_args["name"]
            self.logger.debug("Looking for template filename: %s", filename)
            if not os.path.exists(filename):
                continue

            self.logger.debug("Found template filename: %s", filename)
            template = self.env.get_template(template_args["name"])

            return Response(
                template.render(**template_args["context"]),
                media_type=template_args["media_type"],
                status_code=status_code,
            )

        # if we get here, we have no template to render.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=missing_template_detail(request, templates_dir=self.templates_dir),
        )
        """
        # TODO: return custom fields from settings
        return JSONResponse(
            content=self.missing_resource_fields,
            status_code=status.HTTP_404_NOT_FOUND,
        )
        """

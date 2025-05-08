"""MockStack strategy for using file-based fixtures."""

import logging
import os
from functools import cached_property
from pathlib import Path

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from jinja2 import Environment

from mockstack.config import Settings
from mockstack.intent import (
    looks_like_a_command,
    looks_like_a_search,
    wants_json,
)
from mockstack.strategies.base import BaseStrategy
from mockstack.strategies.create_mixin import CreateMixin
from mockstack.templating import (
    iter_possible_template_arguments,
    templates_env_provider,
)


class FileFixturesStrategy(BaseStrategy, CreateMixin):
    """Strategy for using file-based fixtures."""

    logger = logging.getLogger("FileFixturesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)

        if settings.templates_dir is None:
            raise ValueError("templates_dir is not set")

        self.templates_dir = Path(settings.templates_dir)
        self.enable_templates_for_post = settings.filefixtures_enable_templates_for_post

        self.created_resource_metadata = settings.created_resource_metadata
        self.missing_resource_fields = settings.missing_resource_fields

    def __str__(self) -> str:
        return (
            f"[medium_purple]filefixtures[/medium_purple]\n "
            f"templates_dir: [medium_purple]{self.templates_dir}[/medium_purple].\n "
            f"enable_templates_for_post: [medium_purple]{self.enable_templates_for_post}[/medium_purple]. "
        )

    @cached_property
    def env(self) -> Environment:
        """Jinja2 environment for the filefixtures strategy."""
        return templates_env_provider(self.templates_dir)

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
        request_json = (await request.json()) if wants_json(request) else None
        if self.enable_templates_for_post:
            try:
                return self._response_from_template(request, request_json=request_json)
            except HTTPException as e:
                if e.status_code == status.HTTP_404_NOT_FOUND:
                    # If the template is not found, we try to create the resource with logic below.
                    pass
                else:
                    raise e

        if looks_like_a_search(request):
            # Searching for resources with a complex query that cannot be expressed in a URI.
            return self._response_from_template(request, request_json=request_json)
        elif looks_like_a_command(request):
            # Executing a 'command' of some sort, like a workflow or a batch job.
            # We return a 201 CREATED status code with response from template.
            return self._response_from_template(
                request, request_json=request_json, status_code=status.HTTP_201_CREATED
            )
        else:
            # simulate resource creation:
            return await self._create(
                request,
                env=self.env,
                created_resource_metadata=self.created_resource_metadata,
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

    def _response_from_template(
        self,
        request: Request,
        *,
        request_json: dict | None = None,
        status_code: int = status.HTTP_200_OK,
    ) -> Response:
        for template_args in iter_possible_template_arguments(
            request, request_json=request_json
        ):
            filename = self.templates_dir / template_args["name"]
            self.logger.debug("Looking for template filename: %s", filename)
            if not os.path.exists(filename):
                continue

            self.logger.debug("Found template filename: %s", filename)
            self.update_opentelemetry(request, template_args)
            template = self.env.get_template(template_args["name"])

            return Response(
                template.render(**template_args["context"]),
                media_type=template_args["media_type"],
                status_code=status_code,
            )

        # if we get here, we have no template to render.
        return JSONResponse(
            content=self.missing_resource_fields,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    def update_opentelemetry(self, request: Request, template_args: dict) -> None:
        """Update the opentelemetry span with the file fixtures details."""
        span = request.state.span

        span.set_attribute(
            "mockstack.filefixtures.template_name", template_args["name"]
        )

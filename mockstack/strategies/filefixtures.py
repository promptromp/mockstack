"""MockStack strategy for using file-based fixtures."""

import logging
import os
from pathlib import Path

from fastapi import Request, Response, HTTPException, status
from jinja2 import Environment, FileSystemLoader

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy
from mockstack.templating import (
    iter_possible_template_arguments,
    missing_template_detail,
)


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    logger = logging.getLogger("FileFixturesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.templates_dir = Path(settings.templates_dir)
        self.env = Environment(loader=FileSystemLoader(settings.templates_dir))

    async def apply(self, request: Request) -> Response:
        match request.method:
            case "GET":
                return self._get(request)
            case "POST":
                return self._post(request)
            case "PATCH":
                return self._patch(request)
            case "PUT":
                return self._put(request)
            case "DELETE":
                return self._delete(request)
            case _:
                raise HTTPException(status_code=405, detail="Method not allowed")

    def _delete(self, request: Request) -> Response:
        """Apply the strategy for DELETE requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _patch(self, request: Request) -> Response:
        """Apply the strategy for PATCH requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _put(self, request: Request) -> Response:
        """Apply the strategy for PUT requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _post(self, request: Request) -> Response:
        """Apply the strategy for POST requests."""
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def _get(self, request: Request) -> Response:
        """Apply the strategy for GET requests.

        We try to find a template that matches the request.
        If we find one, we render it and return the response.
        If we don't find one, we raise a 404 error.

        """
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
            )

        # if we get here, we have no template to render.
        raise HTTPException(
            status_code=404,
            detail=missing_template_detail(request, templates_dir=self.templates_dir),
        )

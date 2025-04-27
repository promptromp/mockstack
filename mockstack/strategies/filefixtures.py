"""MockStack strategy for using file-based fixtures."""

import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Generator

from fastapi import Request, Response, HTTPException
from jinja2 import Environment, FileSystemLoader

from mockstack.config import Settings
from mockstack.identifiers import looks_like_id, prefixes
from mockstack.strategies.base import BaseStrategy


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    logger = logging.getLogger("FileFixturesStrategy")

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.templates_dir = Path(settings.templates_dir)
        self.env = Environment(loader=FileSystemLoader(settings.templates_dir))

    def apply(self, request: Request, response: Response | None = None) -> None:
        print(request.headers)
        for template_args in iter_possible_template_arguments(request):
            # iterate over all candidate template arguments, from most specific to least specific.
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


def missing_template_detail(request: Request, *, templates_dir: Path) -> str:
    """Return a detail message for a missing template."""
    return (
        "Template not found for given request. "
        f"path: {request.url.path}, "
        f"query: {request.query_params}, "
        f"templates_dir: {templates_dir}, "
    )


def iter_possible_template_arguments(
    request: Request,
    default_identifier_key: str = "id",
    default_media_type: str = "application/json",
    default_template_name: str = "index.j2",
    template_file_separator: str = "-",
    template_file_extension: str = ".j2",
) -> Generator[dict, None, None]:
    """Infer the template arguments for a given request.

    This includes:

    - Inferring the name for the template file from the URL
    - Inferring the context variables available for the template from the URL and request body.
    - Inferring the response (media) type for the template from the URL and request body.

    There is a fair amount of extrapolation happening here. The philosophy is to provide
    a behavior that "just works" for the majority of the cases encountered in practice.

    """
    path = request.url.path

    name_segments, context = parse_template_name_segments_and_context(
        path,
        default_identifier_key=default_identifier_key,
    )
    media_type = request.headers.get("Content-Type", default_media_type)

    template_name_kwargs = dict(
        template_file_separator=template_file_separator,
        template_file_extension=template_file_extension,
        default_template_name=default_template_name,
    )
    for name in iter_possible_template_filenames(
        name_segments, context, **template_name_kwargs
    ):
        yield dict(
            name=name,
            context=context,
            media_type=media_type,
        )


def parse_template_name_segments_and_context(
    path: str, *, default_identifier_key: str
) -> tuple[list[str], dict[str, str]]:
    """Infer the template name segments and the template context for a given URI path."""
    name_segments: list[str] = []
    context: OrderedDict[str, str] = OrderedDict()
    for segment in (s for s in path.split("/") if s):
        if looks_like_id(segment):
            if name_segments:
                # this is a nested identifier, use the last name segment as the key
                context[name_segments[-1]] = segment
            else:
                # this identifier is unscoped, use our default identifier key
                context[default_identifier_key] = segment
        else:
            name_segments.append(segment)

    return name_segments, context


def iter_possible_template_filenames(
    name_segments: list[str],
    context: dict[str, str],
    *,
    template_file_separator: str,
    template_file_extension: str,
    default_template_name: str,
) -> Generator[str, None, None]:
    """Infer the template filename from the name segments and context.

    We have a cascade of possible filename formats:

    - <n>.<id>.<id>.j2
    - <n>.<id>.j2
    - <n>.j2

    The first option is the most specific, and the last option is the least specific.
    The IDs correspond to any identifiers found in the path of the request, in order.

    """
    if name_segments:
        if context:
            for prefix in prefixes(context.values(), reverse=True):
                yield (
                    f"{template_file_separator.join(name_segments)}.{".".join(prefix)}{template_file_extension}"
                )

        yield template_file_separator.join(name_segments) + template_file_extension

    yield default_template_name

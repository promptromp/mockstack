"""MockStack strategy for using file-based fixtures."""

from fastapi import Request, Response, HTTPException
from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound

from mockstack.config import Settings
from mockstack.identifiers import looks_like_id
from mockstack.strategies.base import BaseStrategy


def infer_template_arguments(
    request: Request,
    default_identifier_key: str = "id",
    default_media_type: str = "application/json",
) -> dict:
    """Infer the template arguments for a given request.

    This includes:

    - Inferring the name for the template file from the URL
    - Inferring the context variables available for the template from the URL and request body.
    - Inferring the response (media) type for the template from the URL and request body.

    There is a fair amount of extrapolation happening here. The philosophy is to provide
    a behavior that "just works" for the majority of the cases encountered in practice.

    """
    path = request.scope["path"]

    name_segments, context = [], {}
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

    # build template filename
    name = "-".join(name_segments) + ".j2"

    media_type = request.headers.get("Content-Type", default_media_type)

    return dict(
        name=name,
        context=context,
        media_type=media_type,
    )


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.env = Environment(loader=FileSystemLoader(settings.templates_dir))

    def apply(self, request: Request, response: Response | None = None) -> None:
        template_args = infer_template_arguments(request)
        try:
            template = self.env.get_template(template_args["name"])
            return Response(
                template.render(**template_args["context"]),
                media_type=template_args["media_type"],
            )
        except TemplateNotFound as e:
            raise HTTPException(status_code=404, detail=str(e))

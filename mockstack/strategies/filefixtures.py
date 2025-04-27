"""MockStack strategy for using file-based fixtures."""

from fastapi import Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from jinja2.exceptions import TemplateNotFound

from mockstack.config import Settings
from mockstack.identifiers import looks_like_id
from mockstack.strategies.base import BaseStrategy


def infer_template_arguments(request: Request) -> dict:
    """Infer the template name for a given request."""
    path = request.scope["path"]

    name_segments, context = [], dict()
    for segment in (s for s in path.split("/") if s):
        if looks_like_id(segment):
            context[name_segments[-1]] = segment
        else:
            name_segments.append(segment)

    # build template filename
    name = "-".join(name_segments) + ".j2"

    return dict(
        name=name,
        context=context,
    )


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.templates = Jinja2Templates(directory=settings.templates_dir)

    def apply(self, request: Request, response: Response | None = None) -> None:
        try:
            return self.templates.TemplateResponse(
                request=request,
                **infer_template_arguments(request),
            )
        except TemplateNotFound as e:
            raise HTTPException(status_code=404, detail=str(e))

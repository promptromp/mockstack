"""MockStack strategy for using file-based fixtures."""

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from mockstack.settings import Settings
from mockstack.strategies.base import BaseStrategy


def template_name_for(path: str) -> str:
    """Get the template name for a given path."""
    return f"{path.replace("/", "-")}.j2"


class FileFixturesStrategy(BaseStrategy):
    """Strategy for using file-based fixtures."""

    def __init__(self, settings: Settings, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.templates = Jinja2Templates(directory=settings.templates_dir)

    def apply(self, request: Request, response: Response) -> None:
        name = template_name_for(request.url.path)
        return self.templates.TemplateResponse(
            request=request,
            name=name,
        )

"""MockStack strategy for using file-based fixtures."""

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy


def looks_like_id(chunk: str) -> bool:
    """Check if a URL path segment looks like an ID.

    Identifiers are typically numeric or alphanumeric (e.g. UUIDs) and are used to identify a resource.

    We apply a couple of simple heuristics to determine if a segment looks like an ID:
    - It must be numeric and have an even number of characters.
    - Or, It must be a hexdecimal string with an even number of characters.
    - Or, It must be a valid UUID4 (36 characters, alphanumeric, and dashes).

    Examples:
    >>> looks_like_id("123")
    True
    >>> looks_like_id("1234567890")
    True
    >>> looks_like_id("1234567890abcdef")
    True
    >>> looks_like_id("3a4e5ad9-17ee-41af-972f-864dfccd4856")
    True
    >>> looks_like_id("project")
    False
    >>> looks_like_id("api")
    False
    >>> looks_like_id("v1")
    False

    """
    N = len(chunk)
    return (
        (N % 2 == 0 and chunk.isdigit())
        or (N % 2 == 0 and all(c in "0123456789abcdef" for c in chunk))
        or (N == 36 and all(c in "0123456789abcdef-" for c in chunk))
    )


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
        return self.templates.TemplateResponse(
            request=request,
            **infer_template_arguments(request),
        )

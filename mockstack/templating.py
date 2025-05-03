"""Templates related functionality."""

from collections import OrderedDict
from functools import partial
from pathlib import Path
from typing import Generator

from fastapi import Request
from jinja2 import Environment, FileSystemLoader

from mockstack.exceptions import raise_for_missing
from mockstack.identifiers import looks_like_id, prefixes


def templates_env_provider(templates_dir: Path | str | None = None) -> Environment:
    """Provide a Jinja2 environment for the templates."""
    # TODO refactor a bit to be more generic for optional dependencies.
    from mockstack.llm import ollama

    loader = FileSystemLoader(templates_dir) if templates_dir else None

    env = Environment(loader=loader)

    env.filters["json_escape"] = json_escape

    if ollama.IS_OLLAMA_AVAILABLE:
        env.globals["ollama"] = ollama.ollama
    else:
        env.globals["ollama"] = partial(
            raise_for_missing,
            "Ollama is not available. Install with optional dependency mockstack[llm] to use it.",
        )

    return env


def missing_template_detail(request: Request, *, templates_dir: Path) -> str:
    """Return a detailed message for a missing template."""
    return (
        "Template not found for given request. "
        f"path: {request.url.path}, "
        f"query: {request.query_params}, "
        f"templates_dir: {templates_dir}, "
    )


def iter_possible_template_arguments(
    request: Request,
    *,
    request_json: dict | None = None,
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

    name_segments, identifiers = parse_template_name_segments_and_identifiers(
        path,
        default_identifier_key=default_identifier_key,
    )
    media_type = request.headers.get("Content-Type", default_media_type)

    context = dict(
        query=dict(request.query_params),
        request_json=request_json,
        headers=dict(request.headers),
        **identifiers,
    )

    template_name_kwargs = dict(
        template_file_separator=template_file_separator,
        template_file_extension=template_file_extension,
        default_template_name=default_template_name,
    )
    for name in iter_possible_template_filenames(
        name_segments, identifiers, **template_name_kwargs
    ):
        yield dict(
            name=name,
            context=context,
            media_type=media_type,
        )


def parse_template_name_segments_and_identifiers(
    path: str, *, default_identifier_key: str
) -> tuple[list[str], dict[str, str]]:
    """Infer the template name segments and the template context for a given URI path."""
    name_segments: list[str] = []
    identifiers: OrderedDict[str, str] = OrderedDict()
    for segment in (s for s in path.split("/") if s):
        if looks_like_id(segment):
            if name_segments:
                # this is a nested identifier, use the last name segment as the key
                identifiers[name_segments[-1]] = segment
            else:
                # this identifier is unscoped, use our default identifier key
                identifiers[default_identifier_key] = segment
        else:
            name_segments.append(segment)

    return name_segments, identifiers


def iter_possible_template_filenames(
    name_segments: list[str],
    identifiers: dict[str, str],
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
        if identifiers:
            for prefix in prefixes(identifiers.values(), reverse=True):
                yield (
                    f"{template_file_separator.join(name_segments)}.{'.'.join(prefix)}{template_file_extension}"
                )

        yield template_file_separator.join(name_segments) + template_file_extension

    yield default_template_name


def json_escape(text: str) -> str:
    """Escape quotes, newlines, tabs, etc. in a string.

    Used as a filter in templates to make the output JSON-compliant.

    """
    return (
        text.replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\f", "\\f")
        .replace("\v", "\\v")
    )

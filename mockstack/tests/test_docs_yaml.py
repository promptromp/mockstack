"""Every YAML example in the Markdown docs parses.

``yaml`` fences are extracted from the README, the docs pages and the example READMEs.
A ``--8<-- "path"`` snippet line is replaced by the file it includes, as
``pymdownx.snippets`` does when the docs site is built.
"""

import re
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

PAGES = sorted(
    {
        REPO_ROOT / "README.md",
        *(REPO_ROOT / "docs").rglob("*.md"),
        *(REPO_ROOT / "examples").rglob("README.md"),
    }
    # docs/README.md is a copy of README.md made by the docs build.
    - {REPO_ROOT / "docs" / "README.md"}
)

FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```ya?ml\b[^\n]*\n(?P<body>.*?)^(?P=indent)```",
    re.MULTILINE | re.DOTALL,
)
SNIPPET = re.compile(r'^[ \t]*--8<--[ \t]+"(?P<path>[^"]+)"[ \t]*$', re.MULTILINE)


def _yaml_blocks(page: Path) -> Iterator[tuple[str, str]]:
    text = page.read_text()
    for match in FENCE.finditer(text):
        body = textwrap.dedent(match.group("body"))
        body = SNIPPET.sub(lambda m: (REPO_ROOT / m.group("path")).read_text(), body)
        line = text.count("\n", 0, match.start()) + 1
        yield f"{page.relative_to(REPO_ROOT)}:{line}", body


BLOCKS = [block for page in PAGES for block in _yaml_blocks(page)]


def test_docs_contain_yaml_examples():
    assert len(BLOCKS) > 10


@pytest.mark.parametrize(("where", "source"), BLOCKS, ids=[w for w, _ in BLOCKS])
def test_yaml_example_parses(where: str, source: str):
    yaml.safe_load(source)

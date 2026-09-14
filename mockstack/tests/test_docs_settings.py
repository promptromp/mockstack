"""Every ``MOCKSTACK__*`` variable named in the docs and examples is a real setting.

Covers the README, contributor docs, docs pages, example READMEs and notebooks, the
Dockerfile and every ``.env.example``. pydantic-settings silently ignores an assignment
in a ``.env`` file that lacks the ``MOCKSTACK__`` prefix, so those are checked too.
"""

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from mockstack.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]

DOCUMENTS = sorted(
    {
        REPO_ROOT / "README.md",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / ".env.example",
        *(REPO_ROOT / "docs").rglob("*.md"),
        *(REPO_ROOT / "examples").rglob("*.md"),
        *(REPO_ROOT / "examples").rglob("*.ipynb"),
        *(REPO_ROOT / "examples").rglob(".env.example"),
    }
    # docs/README.md is a copy of README.md made by the docs build.
    - {REPO_ROOT / "docs" / "README.md"}
)
ENV_FILES = [document for document in DOCUMENTS if document.name == ".env.example"]

ENV_VAR = re.compile(r"MOCKSTACK__[A-Z0-9_]*[A-Z0-9]")
ASSIGNMENT = re.compile(r"^[ \t]*(?P<name>[A-Za-z_]\w*)[ \t]*=", re.MULTILINE)


def _setting_env_vars() -> frozenset[str]:
    names = set()
    for name, field in Settings.model_fields.items():
        names.add(f"MOCKSTACK__{name.upper()}")
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            names.update(f"MOCKSTACK__{name.upper()}__{nested.upper()}" for nested in field.annotation.model_fields)
    return frozenset(names)


SETTING_ENV_VARS = _setting_env_vars()


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_documents_include_env_examples():
    assert REPO_ROOT / ".env.example" in ENV_FILES
    assert len(ENV_FILES) > 1


@pytest.mark.parametrize("document", DOCUMENTS, ids=_relative)
def test_env_vars_name_real_settings(document: Path):
    unknown = sorted(set(ENV_VAR.findall(document.read_text())) - SETTING_ENV_VARS)

    assert unknown == []


@pytest.mark.parametrize("env_file", ENV_FILES, ids=_relative)
def test_env_example_assignments_use_the_prefix(env_file: Path):
    names = ASSIGNMENT.findall(env_file.read_text())

    assert names
    assert [name for name in names if not name.startswith("MOCKSTACK__")] == []

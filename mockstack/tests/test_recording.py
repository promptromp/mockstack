"""Unit tests for mockstack.recording: fixture encoding, confinement and writing."""

from pathlib import Path

import pytest

from mockstack.recording import (
    RECORDED_MARKER,
    encode_fixture,
    is_recorded,
    resolve_inside,
    write_fixture_atomically,
)
from mockstack.templating import templates_env_provider


# Bodies that must survive encoding and rendering byte for byte: Jinja syntax openers,
# carriage returns (Jinja normalises newlines in template text), a "{" right before a
# carriage return, and trailing newlines (Jinja drops one from template source).
ROUND_TRIP_BODIES = [
    "",
    "plain",
    '{"id": "user-1"}',
    "line\n",
    "two newlines\n\n",
    "crlf\r\nlines\r\n",
    "lone\rcarriage return",
    "brace before carriage return {\r",
    "{\r\n",
    "{{\r",
    "{{ user.name }}",
    "{% if x %}y{% endif %}",
    "{# comment #}",
    "{{{ triple",
    "{%}",
    "{% raw %}{{ x }}{% endraw %}",
    "}} and %} closers",
    "日本語 {\n",
    '{"query": "SELECT {{1}} FROM sales_facts"}\n',
    "x" * 100_000 + "{%" * 100,
]


@pytest.fixture(scope="module")
def env():
    return templates_env_provider()


@pytest.mark.parametrize("body", ROUND_TRIP_BODIES)
def test_encoded_fixture_renders_back_to_the_body(env, body):
    assert env.from_string(encode_fixture(body)).render() == body


def test_encoded_fixture_starts_with_the_marker():
    assert encode_fixture('{"a": 1}').startswith(RECORDED_MARKER)


def test_body_without_template_syntax_is_written_as_is():
    assert encode_fixture('{"id": "user-1"}') == RECORDED_MARKER + '{"id": "user-1"}'


def test_marker_renders_to_nothing(env):
    assert env.from_string(RECORDED_MARKER).render() == ""


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (RECORDED_MARKER + "{}", True),
        (RECORDED_MARKER, True),
        ('{"hand": "written"}', False),
        ("\n" + RECORDED_MARKER + "{}", False),
        ("{}" + RECORDED_MARKER, False),
    ],
    ids=["recorded", "marker-only", "hand-written", "marker-not-first", "marker-at-end"],
)
def test_is_recorded(tmp_path, content, expected):
    path = tmp_path / "fixture.json.j2"
    path.write_text(content)
    assert is_recorded(path) is expected


def test_is_recorded_is_false_for_a_missing_file_or_a_directory(tmp_path):
    assert is_recorded(tmp_path / "absent.json.j2") is False
    assert is_recorded(tmp_path) is False


# --- confinement -----------------------------------------------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "fixtures"
    path.mkdir()
    return path


def test_resolve_inside_accepts_a_nested_path_that_does_not_exist_yet(root):
    path = root / "healthy" / "users" / "user-1.json.j2"
    assert resolve_inside(root, path) == path.resolve()


@pytest.mark.parametrize("relative", ["../outside.json.j2", "healthy/../../outside.json.j2", "."])
def test_resolve_inside_rejects_paths_leaving_or_equal_to_the_root(root, relative):
    assert resolve_inside(root, root / relative) is None


def test_resolve_inside_rejects_an_absolute_path_elsewhere(root, tmp_path):
    assert resolve_inside(root, tmp_path / "elsewhere" / "f.json.j2") is None


def test_resolve_inside_rejects_a_symlink_that_escapes_the_root(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert resolve_inside(root, root / "link" / "f.json.j2") is None


def test_resolve_inside_follows_a_symlinked_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "root-link"
    link.symlink_to(real, target_is_directory=True)
    assert resolve_inside(link, link / "users" / "u.json.j2") == real.resolve() / "users" / "u.json.j2"


# --- atomic writes ---------------------------------------------------------------------


def test_write_fixture_atomically_creates_parent_directories(tmp_path):
    path = tmp_path / "healthy" / "users" / "user-1.json.j2"
    write_fixture_atomically(path, "content")
    assert path.read_text() == "content"


def test_write_fixture_atomically_replaces_an_existing_file(tmp_path):
    path = tmp_path / "f.json.j2"
    path.write_text("old")
    write_fixture_atomically(path, "new")
    assert path.read_text() == "new"


def test_written_fixture_is_world_readable_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "f.json.j2"
    write_fixture_atomically(path, "x")
    assert path.stat().st_mode & 0o777 == 0o644
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.json.j2"]


def test_failed_write_keeps_the_old_file_and_removes_the_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "f.json.j2"
    path.write_text("old")

    def disk_full(_fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("mockstack.recording.os.fsync", disk_full)
    with pytest.raises(OSError, match="disk full"):
        write_fixture_atomically(path, "new")
    assert path.read_text() == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.json.j2"]


def test_writer_does_not_translate_newlines(tmp_path):
    path = tmp_path / "f.json.j2"
    write_fixture_atomically(path, "a\nb\n")
    assert path.read_bytes() == b"a\nb\n"


@pytest.mark.parametrize("body", ROUND_TRIP_BODIES)
def test_recorded_file_read_like_the_strategy_renders_back_to_the_body(env, tmp_path, body):
    path = tmp_path / "f.json.j2"
    write_fixture_atomically(path, encode_fixture(body))
    # The way ProxyRulesStrategy.handle_template_result reads a fixture.
    with open(path) as file:
        assert env.from_string(file.read()).render() == body

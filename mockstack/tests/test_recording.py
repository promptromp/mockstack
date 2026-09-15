"""Unit tests for mockstack.recording: fixture encoding, confinement and writing."""

from pathlib import Path

import pytest

from mockstack.recording import RECORDED_MARKER, encode_fixture, is_recorded
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

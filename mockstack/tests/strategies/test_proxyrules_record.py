"""Unit tests for proxyrules record mode. The upstream is mocked; see tests/live for sockets."""

import gzip
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi import Response

from mockstack.constants import RESULT_RULE_HEADER, RESULT_TYPE_HEADER, ProxyRulesRecordMode, ProxyRulesRedirectVia
from mockstack.recording import RECORDED_MARKER, encode_fixture
from mockstack.rules import Rule
from mockstack.strategies.proxyrules import ProxyRulesStrategy


UPSTREAM = "http://upstream.invalid"
BODY = b'{"id": "user-1", "name": "Ada"}'
PASSTHROUGH = {"name": "users-passthrough", "pattern": r"^/users/(.*)", "replacement": f"{UPSTREAM}/users/\\1"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "fixtures"
    path.mkdir()
    return path


@pytest.fixture
def recording(proxyrules_strategy: Callable[..., ProxyRulesStrategy], root: Path) -> Callable[..., ProxyRulesStrategy]:
    """Factory: a reverse-proxy strategy recording into ``root``.

    The rules are ``users-fixture``, serving ``<root>/users/<user_id>.json.j2`` (plus the
    ``fixture`` fields), then ``PASSTHROUGH`` unless ``passthrough=False``.
    """

    def _build(
        mode: str = "missing",
        *,
        fixture: dict[str, Any] | None = None,
        passthrough: bool = True,
        **settings_overrides: Any,
    ) -> ProxyRulesStrategy:
        rules: list[dict[str, Any]] = [
            {
                "name": "users-fixture",
                "pattern": r"^/users/(?P<user_id>[a-z0-9-]+)$",
                "replacement": f"file://{root}/users/{{{{ user_id }}}}.json.j2",
                **(fixture or {}),
            }
        ]
        if passthrough:
            rules.append(PASSTHROUGH)
        return proxyrules_strategy(
            rules=rules,
            proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
            proxyrules_record_mode=ProxyRulesRecordMode(mode),
            proxyrules_record_root=root,
            **settings_overrides,
        )

    return _build


def upstream_response(status: int = 200, content: bytes = BODY) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "application/json"}, content=content)


def result_of(response: Response) -> tuple[int, str | None, str | None]:
    return response.status_code, response.headers.get(RESULT_TYPE_HEADER), response.headers.get(RESULT_RULE_HEADER)


@pytest.mark.asyncio
async def test_missing_fixture_is_recorded_and_served_from_the_file(recording, root, traced_request, upstream_send):
    upstream_send.return_value = upstream_response()
    response = await recording().apply(traced_request("/users/user-1"))
    assert result_of(response) == (200, "record", "users-fixture")
    assert response.body == BODY
    assert response.headers["content-type"] == "application/json"
    assert (root / "users" / "user-1.json.j2").read_text() == RECORDED_MARKER + BODY.decode()
    assert upstream_send.await_count == 1
    assert str(upstream_send.await_args.args[0].url) == f"{UPSTREAM}/users/user-1"


@pytest.mark.asyncio
async def test_recorded_fixture_is_replayed_without_calling_the_upstream(recording, traced_request, upstream_send):
    strategy = recording()
    upstream_send.return_value = upstream_response()
    first = await strategy.apply(traced_request("/users/user-1"))
    second = await strategy.apply(traced_request("/users/user-1"))
    assert result_of(first) == (200, "record", "users-fixture")
    assert result_of(second) == (200, "template", "users-fixture")
    assert second.body == first.body
    assert upstream_send.await_count == 1


CONTENTS = {
    "hand-written": '{"source": "hand-written"}',
    "recorded": encode_fixture('{"source": "recorded"}'),
    "new": encode_fixture('{"source": "new"}'),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "existing", "expected_result", "expected_file", "upstream_calls"),
    [
        ("off", None, (404, "error", "users-fixture"), None, 0),
        ("missing", "hand-written", (200, "template", "users-fixture"), "hand-written", 0),
        ("missing", "recorded", (200, "template", "users-fixture"), "recorded", 0),
        ("overwrite", "hand-written", (200, "template", "users-fixture"), "hand-written", 0),
        ("overwrite", "recorded", (200, "record", "users-fixture"), "new", 1),
        ("overwrite", None, (200, "record", "users-fixture"), "new", 1),
    ],
)
async def test_record_mode_matrix(
    recording, root, traced_request, upstream_send, mode, existing, expected_result, expected_file, upstream_calls
):
    fixture = root / "users" / "user-1.json.j2"
    if existing is not None:
        fixture.parent.mkdir()
        fixture.write_text(CONTENTS[existing])
    upstream_send.return_value = upstream_response(content=b'{"source": "new"}')

    response = await recording(mode).apply(traced_request("/users/user-1"))

    assert result_of(response) == expected_result
    assert upstream_send.await_count == upstream_calls
    assert (fixture.read_text() if fixture.exists() else None) == CONTENTS.get(expected_file)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "upstream", "reason", "expected_level"),
    [
        ("GET", upstream_response(status=404), "upstream status 404, rule serves 200", logging.WARNING),
        ("GET", upstream_response(content=b"\xff\xfe binary"), "the upstream body is not UTF-8", logging.WARNING),
        ("HEAD", upstream_response(), "HEAD responses are never recorded", logging.INFO),
        ("OPTIONS", upstream_response(), "OPTIONS responses are never recorded", logging.INFO),
        (
            "GET",
            httpx.Response(200, headers={"content-type": "application/json", "content-encoding": "br"}, content=BODY),
            "the upstream body is still encoded (br)",
            logging.WARNING,
        ),
    ],
    ids=["status-mismatch", "binary-body", "head", "options", "still-encoded"],
)
async def test_unrecordable_response_is_proxied_and_not_written(
    recording, root, traced_request, upstream_send, caplog, span, method, upstream, reason, expected_level
):
    """M-c: HEAD/OPTIONS is expected on every request to a matched fixture rule while
    it may still be recorded, so it is logged at INFO; every other not-recorded
    reason is a genuine surprise and stays at WARNING."""
    upstream_send.return_value = upstream
    with caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"):
        response = await recording().apply(traced_request("/users/user-1", method=method))
    assert result_of(response) == (upstream.status_code, "proxy", "users-passthrough")
    assert not (root / "users").exists()
    matching = [
        record for record in caplog.records if f"[rule:users-fixture] not recorded: {reason}" in record.getMessage()
    ]
    assert len(matching) == 1
    assert matching[0].levelno == expected_level
    # M2: telemetry is updated for the proxied upstream even when its response is not
    # recorded, the same as a plain passthrough would get.
    span.set_attribute.assert_any_call("mockstack.proxyrules.rewritten_url", f"{UPSTREAM}/users/user-1")


@pytest.mark.asyncio
async def test_gzip_compressed_upstream_body_is_recorded_decoded(recording, root, traced_request, upstream_send):
    """httpx decodes a supported content-encoding while reading the response, and
    ``maybe_update_response_headers`` relabels it ``identity``; that must still record,
    decoded."""
    body = b'{"id": "user-1", "name": "Ada"}'
    upstream_send.return_value = httpx.Response(
        200,
        headers={"content-type": "application/json", "content-encoding": "gzip"},
        content=gzip.compress(body),
    )
    response = await recording().apply(traced_request("/users/user-1"))
    assert result_of(response) == (200, "record", "users-fixture")
    assert response.body == body
    assert (root / "users" / "user-1.json.j2").read_text() == RECORDED_MARKER + body.decode()


@pytest.mark.asyncio
async def test_status_rule_records_a_matching_upstream_status(recording, root, traced_request, upstream_send):
    upstream_send.return_value = upstream_response(status=201)
    request = traced_request(
        "/users/user-1", method="POST", headers={"content-type": "application/json"}, body=b'{"name": "Ada"}'
    )
    response = await recording(fixture={"method": "POST", "status": 201}).apply(request)
    assert result_of(response) == (201, "record", "users-fixture")
    assert (root / "users" / "user-1.json.j2").exists()
    assert upstream_send.await_args.args[0].content == b'{"name": "Ada"}'


@pytest.mark.asyncio
async def test_overwrite_mode_unrecordable_response_leaves_recorded_file_unchanged(
    recording, root, traced_request, upstream_send
):
    """M6(b): a recorded file that is eligible for re-recording is left untouched when
    the fresh upstream response turns out not to be recordable."""
    fixture = root / "users" / "user-1.json.j2"
    fixture.parent.mkdir()
    original = encode_fixture('{"source": "recorded"}')
    fixture.write_text(original)
    upstream_send.return_value = upstream_response(status=404)

    response = await recording("overwrite").apply(traced_request("/users/user-1"))

    assert result_of(response) == (404, "proxy", "users-passthrough")
    assert fixture.read_text() == original


@pytest.mark.asyncio
async def test_recorded_response_carries_the_rules_response_headers(recording, root, traced_request, upstream_send):
    """M6(c): the fixture rule's own ``response_headers`` still apply to a ``record``
    response, the same as they do to a ``template`` one."""
    upstream_send.return_value = upstream_response()

    response = await recording(fixture={"response_headers": {"X-Recorded": "yes"}}).apply(
        traced_request("/users/user-1")
    )

    assert result_of(response) == (200, "record", "users-fixture")
    assert response.headers["x-recorded"] == "yes"


@pytest.mark.asyncio
async def test_body_with_template_syntax_and_crlf_replays_exactly(recording, traced_request, upstream_send):
    body = b'{"template": "{{ user.name }} {% raw %}", "lines": "a\r\nb{\r"}\n'
    strategy = recording()
    upstream_send.return_value = upstream_response(content=body)
    first = await strategy.apply(traced_request("/users/user-1"))
    second = await strategy.apply(traced_request("/users/user-1"))
    assert (first.body, second.body) == (body, body)
    assert result_of(second)[1] == "template"


@pytest.mark.asyncio
async def test_without_a_later_url_rule_the_missing_fixture_is_a_404(recording, traced_request, upstream_send):
    response = await recording(passthrough=False).apply(traced_request("/users/user-1"))
    assert result_of(response) == (404, "error", "users-fixture")
    assert upstream_send.await_count == 0


@pytest.mark.asyncio
async def test_later_fixture_rules_are_skipped_when_looking_for_the_upstream(
    proxyrules_strategy, root, traced_request, upstream_send
):
    strategy = proxyrules_strategy(
        rules=[
            {"name": "users-fixture", "pattern": r"^/users/(.*)$", "replacement": f"file://{root}/users/user.json.j2"},
            {"name": "other-fixture", "pattern": r"^/users/(.*)$", "replacement": f"file://{root}/other.json.j2"},
            PASSTHROUGH,
        ],
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        proxyrules_record_mode=ProxyRulesRecordMode.MISSING,
        proxyrules_record_root=root,
    )
    upstream_send.return_value = upstream_response()

    # M3: a later plain `file:///` fixture rule can never produce a URL, so it must be
    # skipped without being rendered at all -- record ever calling `Rule.apply` on it.
    applied: list[str | None] = []
    original_apply = Rule.apply

    def spy_apply(self: Rule, *args: Any, **kwargs: Any) -> Any:
        applied.append(self.name)
        return original_apply(self, *args, **kwargs)

    with patch.object(Rule, "apply", spy_apply):
        response = await strategy.apply(traced_request("/users/user-1"))

    assert result_of(response) == (200, "record", "users-fixture")
    assert str(upstream_send.await_args.args[0].url) == f"{UPSTREAM}/users/user-1"
    assert not (root / "other.json.j2").exists()
    assert "other-fixture" not in applied
    assert applied == ["users-fixture", "users-passthrough"]


@pytest.mark.asyncio
async def test_upstream_failure_is_a_502_naming_the_fixture_rule(recording, root, traced_request, upstream_send):
    upstream_send.side_effect = httpx.ConnectError("refused")
    response = await recording().apply(traced_request("/users/user-1"))
    assert result_of(response) == (502, "error", "users-fixture")
    assert not (root / "users").exists()


@pytest.mark.asyncio
async def test_fixture_path_outside_the_root_is_not_recorded(
    proxyrules_strategy, root, tmp_path, traced_request, upstream_send, caplog
):
    strategy = proxyrules_strategy(
        rules=[
            {"name": "elsewhere", "pattern": r"^/users/(.*)$", "replacement": f"file://{tmp_path}/elsewhere/u.json.j2"},
            PASSTHROUGH,
        ],
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        proxyrules_record_mode=ProxyRulesRecordMode.MISSING,
        proxyrules_record_root=root,
    )
    # M4: the outside-root WARNING is logged once per rule, not once per request.
    with caplog.at_level(logging.WARNING, logger="ProxyRulesStrategy"):
        first = await strategy.apply(traced_request("/users/user-1"))
        second = await strategy.apply(traced_request("/users/user-1"))
    assert result_of(first) == (404, "error", "elsewhere")
    assert result_of(second) == (404, "error", "elsewhere")
    assert upstream_send.await_count == 0
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "outside proxyrules_record_root" in record.getMessage()
    ]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_dotdot_in_rendered_path_is_not_recorded(proxyrules_strategy, root, traced_request, upstream_send):
    """M1: a rendered fixture path containing ``..`` is rejected before it is ever
    considered for recording (and by ``handle_template_result`` in the normal path)."""
    strategy = proxyrules_strategy(
        rules=[
            {
                "name": "users-fixture",
                "pattern": r"^/users/(?P<user_id>[a-z0-9-]+)$",
                "replacement": f"file://{root}/users/../{{{{ user_id }}}}.json.j2",
            },
            PASSTHROUGH,
        ],
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        proxyrules_record_mode=ProxyRulesRecordMode.MISSING,
        proxyrules_record_root=root,
    )
    response = await strategy.apply(traced_request("/users/user-1"))
    assert result_of(response) == (404, "error", "users-fixture")
    assert upstream_send.await_count == 0
    assert list(root.rglob("*")) == []


@pytest.mark.asyncio
async def test_write_failure_is_a_500_naming_the_fixture_rule(
    recording, root, traced_request, upstream_send, monkeypatch, caplog
):
    def read_only(path: Path, _text: str) -> None:
        raise PermissionError(f"read-only: {path}")

    monkeypatch.setattr("mockstack.strategies.proxyrules.write_fixture_atomically", read_only)
    upstream_send.return_value = upstream_response()
    fixture = root / "users" / "user-1.json.j2"
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await recording().apply(traced_request("/users/user-1"))
    assert result_of(response) == (500, "error", "users-fixture")
    assert not fixture.exists()
    # M-d: a dedicated ERROR line names the fixture rule and the path that could not
    # be written, distinct from `apply`'s generic unhandled-error log.
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert any(
        "[rule:users-fixture] could not record" in record.getMessage() and str(fixture.resolve()) in record.getMessage()
        for record in errors
    )


@pytest.mark.asyncio
async def test_recording_sets_span_attributes(recording, root, traced_request, upstream_send, span):
    upstream_send.return_value = upstream_response()
    await recording().apply(traced_request("/users/user-1"))
    span.set_attribute.assert_any_call("mockstack.proxyrules.result_type", "record")
    span.set_attribute.assert_any_call(
        "mockstack.proxyrules.recorded_path", str((root / "users" / "user-1.json.j2").resolve())
    )


# --- scrubber --------------------------------------------------------------------------
#
# The strategy fixture applies settings_overrides via `model_copy` (unvalidated), so these
# pass the scrubber function itself rather than a "module:function" string -- Settings (and
# its ImportString field) owns loading a string reference; see test_config.py.

SCRUBBER_CALLS: list[dict[str, Any]] = []


def mask_names(body: str, *, request: Any, rule_name: str | None, path: Path) -> str | None:
    SCRUBBER_CALLS.append({"path": request.url.path, "rule_name": rule_name, "file": path})
    return body.replace("Ada", "***")


def skip_everything(body: str, *, request: Any, rule_name: str | None, path: Path) -> str | None:
    return None


def return_bytes(body: str, *, request: Any, rule_name: str | None, path: Path) -> Any:
    return body.encode()


def raise_error(body: str, *, request: Any, rule_name: str | None, path: Path) -> str | None:
    raise RuntimeError("scrubber failed")


@pytest.mark.asyncio
async def test_scrubbed_body_is_written_and_served(recording, root, traced_request, upstream_send):
    SCRUBBER_CALLS.clear()
    upstream_send.return_value = upstream_response()
    response = await recording(proxyrules_record_scrubber=mask_names).apply(traced_request("/users/user-1"))
    fixture = root / "users" / "user-1.json.j2"
    assert result_of(response) == (200, "record", "users-fixture")
    assert response.body == b'{"id": "user-1", "name": "***"}'
    assert "Ada" not in fixture.read_text()
    assert [{"path": "/users/user-1", "rule_name": "users-fixture", "file": fixture.resolve()}] == SCRUBBER_CALLS


@pytest.mark.asyncio
async def test_scrubber_returning_none_skips_recording(recording, root, traced_request, upstream_send, caplog):
    """A scrubber returning None is the documented, intentional way to skip recording an
    endpoint, so the not-recorded reason is logged at INFO, not WARNING."""
    upstream_send.return_value = upstream_response()
    strategy = recording(proxyrules_record_scrubber=skip_everything)
    with caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"):
        response = await strategy.apply(traced_request("/users/user-1"))
    assert result_of(response) == (200, "proxy", "users-passthrough")
    assert response.body == BODY
    assert not (root / "users").exists()
    matching = [record for record in caplog.records if "not recorded: the scrubber skipped it" in record.getMessage()]
    assert len(matching) == 1
    assert matching[0].levelno == logging.INFO
    assert not any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.asyncio
async def test_scrubber_returning_a_non_string_is_a_500(recording, root, traced_request, upstream_send, caplog):
    upstream_send.return_value = upstream_response()
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await recording(proxyrules_record_scrubber=return_bytes).apply(traced_request("/users/user-1"))
    assert result_of(response) == (500, "error", "users-fixture")
    assert not (root / "users").exists()
    # M-d: a dedicated ERROR line names the fixture rule and the path, distinct from
    # `apply`'s generic unhandled-error log.
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert any("[rule:users-fixture] scrubber failed for" in record.getMessage() for record in errors)


@pytest.mark.asyncio
async def test_scrubber_that_raises_is_a_500_and_nothing_is_written(
    recording, root, traced_request, upstream_send, caplog
):
    upstream_send.return_value = upstream_response()
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await recording(proxyrules_record_scrubber=raise_error).apply(traced_request("/users/user-1"))
    assert result_of(response) == (500, "error", "users-fixture")
    assert not (root / "users").exists()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert any("[rule:users-fixture] scrubber failed for" in record.getMessage() for record in errors)

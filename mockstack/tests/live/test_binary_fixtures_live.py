"""Live tests for fixture files that are served verbatim because they are not UTF-8.

The unit tests call the strategy directly. Here a multi-megabyte binary fixture goes
through the whole app, whose HTTP middleware re-streams every response body, and over a
real socket, so the bytes, ``Content-Length`` and framing are what a client receives,
on a connection that is then reused.
"""

import hashlib

import httpx
import pytest


pytestmark = pytest.mark.slow

# 3 MB of random-looking bytes, the same on every run: not UTF-8, and large enough to be
# sent in several writes.
EXPORT = hashlib.shake_256(b"export").digest(3 * 1024 * 1024)


@pytest.fixture(scope="module")
def exports(tmp_path_factory, mockstack_server):
    """Mockstack serving a binary export and a JSON template."""
    fixtures = tmp_path_factory.mktemp("fixtures")
    export = fixtures / "export.bin"
    export.write_bytes(EXPORT)
    order = fixtures / "order.json.j2"
    order.write_text('{"id": {{ order_id | tojson }}}')
    return mockstack_server(
        [
            {"name": "export", "pattern": r"^/exports/latest$", "replacement": f"file://{export}"},
            {"name": "order", "pattern": r"^/orders/(?P<order_id>[a-z0-9-]+)$", "replacement": f"file://{order}"},
        ]
    )


def test_binary_fixture_is_sent_byte_for_byte_on_a_reused_connection(exports):
    with httpx.Client(base_url=exports.base_url, timeout=10) as client:
        export = client.get("/exports/latest")
        head = client.head("/exports/latest")
        following = client.get("/orders/ord-1")

    assert (export.status_code, export.headers["x-mockstack-result"], export.headers["x-mockstack-rule"]) == (
        200,
        "template",
        "export",
    )
    assert export.content == EXPORT
    assert export.headers["content-type"] == "application/octet-stream"
    assert export.headers["content-length"] == str(len(EXPORT))
    # HEAD gets the headers a GET would, and no body to misread as the next response.
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(EXPORT))
    assert head.headers["x-mockstack-result"] == "template"
    assert following.status_code == 200
    assert following.json() == {"id": "ord-1"}

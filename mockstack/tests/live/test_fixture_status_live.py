"""Live tests for fixture rules that set ``status`` and ``response_headers``.

Message framing only really happens on a socket: a 204 or 304 must go out without
content, or a client reusing the connection reads the stray body as the start of its
next response. The documented statuses and headers are covered by ``test_cookbook.py``
(recipe 8), which runs the shipped rules file.
"""

import httpx
import pytest


pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def orders(tmp_path_factory, mockstack_server):
    """Mockstack serving one order fixture as a 204, a 304 or a 200."""
    fixture = tmp_path_factory.mktemp("fixtures") / "order.json.j2"
    fixture.write_text('{"id": {{ order_id | tojson }}}')
    pattern = r"^/orders/(?P<order_id>[a-z0-9-]+)$"
    return mockstack_server(
        [
            {
                "name": "order-deleted",
                "method": "DELETE",
                "pattern": pattern,
                "status": 204,
                "replacement": f"file://{fixture}",
            },
            {
                "name": "order-not-modified",
                "method": "GET",
                "pattern": pattern,
                "headers": {"if-none-match": ".+"},
                "status": 304,
                "response_headers": {"ETag": '"v1"'},
                "replacement": f"file://{fixture}",
            },
            {
                "name": "order",
                "method": "GET",
                "pattern": pattern,
                "replacement": f"file://{fixture}",
            },
        ]
    )


@pytest.mark.parametrize(
    ("method", "headers", "status", "rule", "etag"),
    [
        ("DELETE", {}, 204, "order-deleted", None),
        ("GET", {"If-None-Match": '"v1"'}, 304, "order-not-modified", '"v1"'),
    ],
    ids=["204", "304"],
)
def test_bodyless_fixture_status_keeps_the_connection_usable(orders, method, headers, status, rule, etag):
    with httpx.Client(base_url=orders.base_url, timeout=10) as client:
        bodyless = client.request(method, "/orders/ord-1", headers=headers)
        following = client.get("/orders/ord-1")

    assert (bodyless.status_code, bodyless.headers["x-mockstack-result"], bodyless.headers["x-mockstack-rule"]) == (
        status,
        "template",
        rule,
    )
    assert bodyless.content == b""
    assert "content-length" not in bodyless.headers
    assert bodyless.headers.get("etag") == etag
    assert following.status_code == 200
    assert following.headers["x-mockstack-rule"] == "order"
    assert following.json() == {"id": "ord-1"}

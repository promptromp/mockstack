"""Constants for mockstack."""

from enum import StrEnum


ENV_PREFIX = "mockstack__"
ENV_FILE = ".env"
ENV_NESTED_DELIMITER = "__"

# Template files are identified by a file:// URL prefix.
PROXYRULES_FILE_TEMPLATE_PREFIX = "file:///"

SENSITIVE_HEADERS = ["authorization", "cookie", "set-cookie"]

# Response headers the ASGI server supplies itself. uvicorn prepends its own `date` and
# `server` to every response without checking the app's headers, so forwarding a proxied
# upstream's copies would send each of them twice.
SERVER_SUPPLIED_RESPONSE_HEADERS = ("date", "server")


# Response headers stamped by the proxyrules strategy so callers can assert which
# rule served a request (and that a fixture, not the real upstream, answered).
RESULT_RULE_HEADER = "X-Mockstack-Rule"
RESULT_TYPE_HEADER = "X-Mockstack-Result"


# Headers that describe a single hop and must not be forwarded by a proxy (RFC 9110 §7.6.1).
# Headers named in a Connection header value are stripped too (see strip_hop_by_hop).
# content-length is deliberately not listed: the proxy handles it separately in each
# direction because the body is buffered.
HOP_BY_HOP_HEADERS = (
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
)

# Response headers a proxyrules fixture rule may not set in ``response_headers``: message
# framing and connection headers, the ASGI server's own, and the result headers.
MOCKSTACK_OWNED_RESPONSE_HEADERS = frozenset(
    {
        *HOP_BY_HOP_HEADERS,
        "content-length",
        *SERVER_SUPPLIED_RESPONSE_HEADERS,
        RESULT_RULE_HEADER.lower(),
        RESULT_TYPE_HEADER.lower(),
    }
)


class ProxyRulesRedirectVia(StrEnum):
    """The type of redirect to use for the proxy rules strategy.

    - HTTP_* type redirects are handled by using a Http redirect response.
    - REVERSE_PROXY type redirects are handled by using a reverse proxy to the target URL
        which is opaque to the client.

    """

    HTTP_TEMPORARY_REDIRECT = "http_307_temporary"
    HTTP_PERMANENT_REDIRECT = "http_301_permanent"
    REVERSE_PROXY = "reverse_proxy"

"""Constants for mockstack."""

from enum import StrEnum

ENV_PREFIX = "mockstack__"
ENV_FILE = ".env"
ENV_NESTED_DELIMITER = "__"

# Template files are identified by a file:// URL prefix.
PROXYRULES_FILE_TEMPLATE_PREFIX = "file:///"

SENSITIVE_HEADERS = ["authorization", "cookie", "set-cookie"]

# See https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Encoding
CONTENT_ENCODING_COMPRESSED = (
    "gzip",
    "compress",
    "deflate",
    "br",
    "zstd",
    "dcb",
    "dcz",
)


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


class ProxyRulesRedirectVia(StrEnum):
    """The type of redirect to use for the proxy rules strategy.

    - HTTP_* type redirects are handled by using a Http redirect response.
    - REVERSE_PROXY type redirects are handled by using a reverse proxy to the target URL
        which is opaque to the client.

    """

    HTTP_TEMPORARY_REDIRECT = "http_307_temporary"
    HTTP_PERMANENT_REDIRECT = "http_301_permanent"
    REVERSE_PROXY = "reverse_proxy"

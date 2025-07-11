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


class ProxyRulesRedirectVia(StrEnum):
    """The type of redirect to use for the proxy rules strategy.

    - HTTP_* type redirects are handled by using a Http redirect response.
    - REVERSE_PROXY type redirects are handled by using a reverse proxy to the target URL
        which is opaque to the client.

    """

    HTTP_TEMPORARY_REDIRECT = "http_307_temporary"
    HTTP_PERMANENT_REDIRECT = "http_301_permanent"
    REVERSE_PROXY = "reverse_proxy"

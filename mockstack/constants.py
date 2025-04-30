"""Constants for mockstack."""

from enum import StrEnum

# proxyrules strategy constants


class ProxyRulesRedirectVia(StrEnum):
    """The type of redirect to use for the proxy rules strategy.

    - HTTP_* type redirects are handled by using a Http redirect response.
    - REVERSE_PROXY type redirects are handled by using a reverse proxy to the target URL
        which is opaque to the client.

    """

    HTTP_TEMPORARY_REDIRECT = "http_307_temporary"
    HTTP_PERMANENT_REDIRECT = "http_301_permanent"
    REVERSE_PROXY = "reverse_proxy"

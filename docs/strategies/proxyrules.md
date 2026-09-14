# ProxyRules Strategy

The `ProxyRulesStrategy` is a powerful strategy that allows you to define rules for redirecting or proxying requests to other services. It's particularly useful when you need to mix mock responses with real service calls.

## Overview

This strategy:

- Uses a YAML configuration file to define routing rules
- Supports multiple redirection methods (HTTP redirects or reverse proxy)
- Can simulate resource creation for unmatched requests
- Provides OpenTelemetry integration for observability

## Configuration

The strategy requires the following configuration:

```python
settings = Settings(
    strategy="proxyrules",
    proxyrules_rules_filename="/path/to/rules.yaml",
    proxyrules_redirect_via="REVERSE_PROXY",  # or "HTTP_TEMPORARY_REDIRECT" or "HTTP_PERMANENT_REDIRECT"
    proxyrules_reverse_proxy_timeout=10.0,
    proxyrules_simulate_create_on_missing=False,
)
```

## Rules Configuration

Rules are defined in a YAML file with the following structure:

```yaml
rules:
  - name: "user-service"
    pattern: "^/api/v1/users/(.*)"
    replacement: "http://user-service/api/v1/users/\1"
    method: "GET"  # optional, if not specified matches all methods
```

### Rule Properties

- `name`: Optional identifier for the rule (used in telemetry)
- `pattern`: Regular expression pattern to match against the request path
- `replacement`: URL template to redirect to (can use capture groups from pattern)
- `method`: Optional HTTP method to match (if not specified, matches all methods)
- `headers`: Optional mapping of header name -> regex. Every listed header must be
  present and its whole value must match the regex (`re.fullmatch`). Names are
  case-insensitive. Use `".*"` to require presence only.
- `query`: Optional mapping of query parameter -> regex, same semantics.

All predicates on a rule are ANDed. Rules are evaluated in order and the first
match wins, so put narrow, predicate-bearing rules before broad passthroughs:

```yaml
rules:
  - name: project-eval               # only stamped eval traffic
    method: GET
    pattern: ^/projects/api/v2/project/(?P<id>[^/]+)$
    headers:
      x-request-eval-scenario: ".*"
    replacement: file:///fixtures/projects/project.json.j2
  - name: projects-passthrough        # everything else reaches the real service
    pattern: ^/projects/(.*)
    replacement: https://projects.example/\1
```

## Redirection Methods

The strategy supports three redirection methods:

1. **HTTP Temporary Redirect (307)**
    - Client makes a new request to the target URL
    - Preserves the original HTTP method

2. **HTTP Permanent Redirect (301)**
    - Client makes a new request to the target URL
    - Browsers may cache the redirect

3. **Reverse Proxy**
    - Server forwards the request to the target service
    - Client is unaware of the redirection
    - Useful when you need to work with clients that do not handle HTTP redirects gracefully.
    - Request and response bodies are fully buffered. Hop-by-hop headers
      (`Connection`, `Transfer-Encoding`, `Upgrade`, ...) and `Content-Length`
      are stripped and recomputed on each side, so chunked clients and
      chunked upstreams both work.

## Resource Creation Simulation

When `proxyrules_simulate_create_on_missing` is enabled and a POST request doesn't match any rules, the strategy will simulate resource creation by:

1. Injecting metadata fields into the response
2. Returning a 201 CREATED status code
3. Echoing back the request body with added metadata

The default metadata fields are controlled via the configuration file and at the time of writing are as follows:

```json
{
    "id": "{{ uuid4() }}",
    "createdAt": "{{ utcnow().isoformat() }}",
    "updatedAt": "{{ utcnow().isoformat() }}",
    "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
    "status": {
        "code": "OK",
        "error_code": null
    }
}
```

## OpenTelemetry Integration

The strategy automatically adds the following OpenTelemetry attributes:

- `mockstack.proxyrules.rule_name`: The name of the matched rule (if specified)
- `mockstack.proxyrules.rule_method`: The HTTP method the rule matches (if specified)
- `mockstack.proxyrules.rule_pattern`: The pattern used to match the request
- `mockstack.proxyrules.rule_replacement`: The replacement URL template
- `mockstack.proxyrules.rewritten_url`: The final URL after applying the rule

## Example Rules

Here are some example rules:

```yaml
rules:
  # Redirect all GET requests to /api/v1/users/* to the user service
  - name: "user-service-get"
    pattern: "^/api/v1/users/(.*)"
    replacement: "http://user-service/api/v1/users/\1"
    method: "GET"

  # Proxy all POST requests to /api/v1/orders to the order service
  - name: "order-service-post"
    pattern: "^/api/v1/orders"
    replacement: "http://order-service/api/v1/orders"
    method: "POST"

  # Redirect all requests to /api/v1/products to the product service
  - name: "product-service"
    pattern: "^/api/v1/products/(.*)"
    replacement: "http://product-service/api/v1/products/\1"
```

## File Templates

A `replacement` starting with `file:///` serves a Jinja2 template instead of proxying.
The path is an **absolute filesystem path**; `templates_dir` is not consulted.

```yaml
rules:
  - name: project-fixture
    method: GET
    pattern: ^/projects/api/v2/project/(?P<id>[^/]+)$
    replacement: file:///fixtures/projects/project.json.j2
```

The response content type comes from the file suffix, ignoring a trailing `.j2`
(`project.json.j2` -> `application/json`). Templates always return HTTP 200.

### Template context

| Variable | Contents |
| --- | --- |
| `path`, `method` | Request path and method |
| `query` | Query parameters as a dict |
| `headers` | Request headers as a dict, names lower-cased |
| `request_json` | Parsed JSON body, or `None` when the body is empty or not JSON |
| `id`, `<segment>` | Identifiers inferred from the path, as in the filefixtures strategy |

## Error Handling

When no matching rule is found and resource creation simulation is disabled, the strategy returns a 404 NOT FOUND response.

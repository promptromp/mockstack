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

- `name`: Optional identifier for the rule (used in telemetry and in the
  `X-Mockstack-Rule` response header)
- `pattern`: Regular expression pattern to match against the request path
  (`re.match`, so it is anchored at the start of the path)
- `replacement`: URL template to redirect to (can use capture groups from pattern)
- `method`: Optional HTTP method to match, case-insensitive (if not specified,
  matches all methods)
- `headers`: Optional mapping of header name -> regex. Every listed header must be
  present and its whole value must match the regex (`re.fullmatch`). Names are
  case-insensitive. Use `".*"` to require presence only. A repeated header is
  matched on its first value.
- `query`: Optional mapping of query parameter -> regex; same regex semantics;
  parameter names are case-sensitive. A repeated query parameter
  (`?tag=a&tag=b`) is matched on its last value.
- `body`: Optional regex searched (`re.search`) in the decoded request body.
- `json`: Optional mapping of dotted JSON path -> regex, fully matched against the
  JSON text form of the value at that path (`query`, `filter.client.id`,
  `items.0.name`). Strings are matched raw, without quotes; every other value is
  matched as a compact JSON literal: `true`, `false`, `null`, `1.5`,
  `{"a":1,"b":2}` (keys sorted, no spaces). A path that is absent never matches,
  while a present `null` matches as the text `null`. A rule with `body`/`json`
  never matches a request without a body.

Predicate values must be strings. YAML reads unquoted `2`, `true` or `2024` as
numbers and booleans; mockstack converts them back with `str()`, which turns `true`
into `True`, so quote them: `x-api-version: "2"`, `active: "true"`. A predicate with
no value at all (`x-foo:`) is rejected.

Every regex (`pattern` and each predicate) is compiled and validated when the rules
file is loaded, at startup. An invalid regex, or any of the other load-time errors
described below, stops mockstack from starting with the rule's name in the error,
instead of failing on the first request that reaches the broken rule.

All predicates on a rule are ANDed. Rules are evaluated in order and the first
match wins, so put narrow, predicate-bearing rules before broad passthroughs:

```yaml
rules:
  - name: project-eval               # only stamped eval traffic
    method: GET
    pattern: ^/projects/api/v1/project/(?P<id>[^/]+)$
    headers:
      x-request-eval-scenario: ".*"
    replacement: file:///fixtures/projects/project.json.j2
  - name: projects-passthrough        # everything else reaches the real service
    pattern: ^/projects/(.*)
    replacement: https://projects.example/\1
```

Body predicates make it possible to mock endpoints where every request shares one
path and the intent lives in the payload, such as SQL gateways:

```yaml
  - name: analytics-sales-eval
    method: POST
    pattern: ^/analytics/v1/sql$
    headers:
      x-request-eval-scenario: ".*"
    json:
      query: "(?is).*FROM\\s+sales_facts.*"
    replacement: file:///fixtures/analytics/sales_facts.json.j2
```

The body is read once per request and cached by Starlette, so predicates do not
interfere with reverse proxying or resource-creation simulation.

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
      (`Connection`, `Transfer-Encoding`, `Upgrade`, ..., plus every header named
      in a `Connection` value) are stripped in both directions, and
      `Content-Length` is recomputed for the buffered body, so chunked clients and
      chunked upstreams both work. A response to `HEAD` keeps the upstream's
      `Content-Length`; `1xx`, `204` and `304` responses carry none.
    - Repeated response headers, such as several `Set-Cookie` headers, are passed
      through one by one rather than merged.

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

## Result headers

Every response the `proxyrules` strategy returns -- including its own error
responses -- carries:

| Header | Value |
| --- | --- |
| `X-Mockstack-Result` | `template`, `proxy`, `redirect`, `create`, `missing` or `error` |
| `X-Mockstack-Rule` | The matched rule's `name` (or its `pattern` when unnamed); absent when no rule matched |

| `X-Mockstack-Result` | Status | Meaning |
| --- | --- | --- |
| `template` | 200 | A `file:///` fixture was rendered |
| `proxy` | Upstream's | The request was reverse-proxied to the rewritten URL |
| `redirect` | 301 / 307 | An HTTP redirect to the rewritten URL |
| `create` | 201 | No rule matched; resource creation was simulated |
| `missing` | 404 | No rule matched |
| `error` | 404 | A rule matched but its fixture file does not exist (or its path contains `..`) |
| `error` | 500 | A fixture failed to render, a template replacement failed, or another internal failure |
| `error` | 502 | The upstream request failed |
| `error` | 504 | The upstream request timed out |

Every response the strategy returns carries the headers; a 404 or 5xx stamped
`error` came from mockstack, not a fixture. Test harnesses should assert on these to
turn a silently proxied request into a failure. An unstamped 5xx response means the
ASGI layer itself failed (outside the strategy), not that `proxyrules` returned it.

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
`file://` followed directly by an absolute path (i.e. `file:///abs/path`, three
slashes total) is the canonical form; when building the path from a variable that
already starts with `/` (e.g. `${FIXTURES_DIR}`), write `file://${FIXTURES_DIR}/...`
(two slashes) so the interpolated value supplies the third -- `file:///${FIXTURES_DIR}/...`
would otherwise double up into a four-slash, `//`-rooted path.

```yaml
rules:
  - name: project-fixture
    method: GET
    pattern: ^/projects/api/v1/project/(?P<id>[^/]+)$
    replacement: file:///fixtures/projects/project.json.j2
```

The response content type comes from the file suffix, ignoring a trailing `.j2`
(`project.json.j2` -> `application/json`). A successfully rendered template always
returns HTTP 200; see [Error Handling](#error-handling) for the failure cases.

### Template context

| Variable | Contents |
| --- | --- |
| `path`, `method` | Request path and method |
| `query` | Query parameters as a dict (a repeated parameter keeps its last value) |
| `headers` | Request headers as a dict, names lower-cased (a repeated header keeps its first value) |
| `request_json` | Parsed JSON body, or `None` when the body is empty or not JSON |
| `groups` | Tuple of the positional groups from `pattern` (`None` for a group that did not participate) |
| `<named group>` | Each named group from `pattern`, e.g. `id` for `(?P<id>[^/]+)` |
| `id`, `<segment>` | Identifiers inferred from the path, as in the filefixtures strategy |

When names collide, the reserved names (`path`, `method`, `query`, `headers`,
`request_json`, `groups`) always win, and named groups override identifiers
inferred from the path. A named group that would shadow a reserved name, such as
`(?P<headers>...)`, is rejected when the rules are loaded. A named group that did
not participate in the match (an unmatched optional group) is absent from the
context rather than `None`.

### Dynamic replacements

A `replacement` containing `{{ ... }}` or `{% ... %}` is rendered as a Jinja2
template in its own right, with the same context as file templates, including every
**named group** from `pattern` and the `groups` tuple of positional groups. This
lets one rule fan out to per-scenario fixture directories:

```yaml
  - name: project-eval
    method: GET
    pattern: ^/projects/api/v1/project/(?P<id>[^/]+)$
    headers:
      x-request-eval-scenario: "[a-z0-9_-]+"
    replacement: file:///fixtures/{{ headers['x-request-eval-scenario'] }}/projects/project.{{ id }}.json.j2
```

The replacement is compiled once, when the rules are loaded, so a Jinja syntax
error stops mockstack from starting. In this mode regex backreferences (`\1`,
`\g<id>`) are **not** expanded -- the `replacement` string is rendered directly and
`re.sub` never runs, so use `{{ groups[0] }}` (positional) or the named group
(`{{ id }}`) instead. A replacement that mixes Jinja delimiters with a backreference
is rejected at load. The URL fragment is not carried into the rendered result
either; only plain `re.sub` mode appends it (URL-encoded) to the path it rewrites.
A `replacement` with no Jinja delimiters keeps the plain `re.sub` behaviour, and
backreferences work as before.

Template replacements are rendered with strict undefined: referencing a header,
query parameter, JSON key or group that is not there is an error, not an empty
string. The request is answered with a 500 stamped `X-Mockstack-Result: error` and
the rule's `X-Mockstack-Rule`, and the error is logged, instead of silently
rendering a path such as `file:///fixtures//projects/project.json.j2`. Give
optional values an explicit fallback, e.g.
`{{ headers.get('x-request-eval-scenario', 'default') }}`.

!!! warning
    A rendered `file://` path or proxied URL must never be built from an
    unconstrained request value. mockstack rejects any rendered template path
    containing `..`, but a predicate like `x-request-eval-scenario: ".*"` still lets
    a header select an arbitrary sibling fixture *within* the intended directory tree
    (and a rendered replacement that proxies, `https://{{ ... }}`, lets request data
    choose the upstream entirely -- mockstack is already an open reverse proxy; only
    expose it on trusted networks). A rendered request value must also never be the
    *leading* element of a `file://` path -- e.g.
    `file://{{ headers['x-root'] }}/f.json` lets a header select an arbitrary
    absolute path (it need only start with `/`), which the `..` guard cannot catch
    since no `..` segment is ever involved. Restrict predicates feeding a rendered
    path or URL to the character classes you actually expect, e.g. `[a-z0-9_-]+`.

## Testing evaluation suites

A single mockstack instance can sit in front of a real service and serve fixtures
only to evaluation traffic: stamp eval requests with a header (e.g.
`X-Request-Eval-Scenario: healthy`), put a narrow, header-gated rule ahead of a
broad passthrough for the same path prefix, and point the fixture rule's
`replacement` at a `file:///` template under a per-scenario directory. Every
other request -- unstamped, or one whose header value fails the predicate --
fails open and is reverse-proxied to the real service untouched. A *stamped*
request naming a scenario with no fixture on disk still matches the eval rule
and does not fall through to the passthrough: it gets a 404 stamped
`X-Mockstack-Result: error` with body `{"error": "Template file not found."}`, so
evaluators see a missing fixture as an error, not a passthrough.

Have the eval harness assert `X-Mockstack-Result` (and, ideally,
`X-Mockstack-Rule`) on every response instead of only checking the body: a rule
that stops matching -- a path change upstream, a typo'd header -- then fails the
run instead of silently exercising the real service with fixture inputs.

See
[`examples/proxyrules-eval-isolation`](https://github.com/promptromp/mockstack/tree/main/examples/proxyrules-eval-isolation)
for a complete worked example, including a live test that runs its rules file
and fixtures for real.

## Error Handling

When no matching rule is found and resource creation simulation is disabled, the
strategy returns a 404 NOT FOUND response stamped `X-Mockstack-Result: missing`.

Every other failure is answered by the strategy itself, stamped
`X-Mockstack-Result: error` and, once a rule has matched, `X-Mockstack-Rule`,
instead of surfacing as a bare, unstamped 500 from Starlette's
`ServerErrorMiddleware`:

| Failure | Status | Body |
| --- | --- | --- |
| The rendered fixture path does not exist, or contains `..` | 404 | `{"error": "Template file not found."}` |
| The fixture fails to render | 500 | `{"error": "An internal error occurred while rendering the template."}` |
| The upstream is unreachable, resets the connection or breaks the protocol | 502 | `{"error": "mockstack: upstream request failed"}` |
| The upstream does not answer within `proxyrules_reverse_proxy_timeout` | 504 | `{"error": "mockstack: upstream request timed out"}` |
| Anything else, e.g. a template replacement referencing a missing value, an unrecognised `proxyrules_redirect_via`, or a malformed JSON body on the resource-creation path | 500 | `{"error": "mockstack: internal error"}` |

The rendered fixture path is never echoed back in a response body; it is only
logged. Upstream failures are logged at WARNING; other failures at ERROR, with a
traceback and the rule name. If the client disconnects before its request body has
been read, no response is sent.

A broken rules file fails at startup rather than per request: YAML that does not
parse, and, naming the offending rule, an invalid regex, an invalid Jinja
replacement, a predicate without a value, a named group that shadows a reserved
template variable, or a replacement that mixes Jinja delimiters with a
backreference.

# ProxyRules Strategy

The `ProxyRulesStrategy` routes each request through an ordered list of rules. A rule
can serve a Jinja fixture file, reverse-proxy the request to a real service, or
redirect the client there, so a single mockstack instance can mix mock responses with
real service calls.

See also the [ProxyRules cookbook](../guides/proxyrules-cookbook.md): tested,
copy-paste recipes for the most common setups.

## Overview

This strategy:

- Reads its rules from a YAML file; rules are tried in order and the first match wins
- Matches requests on a path regex, the HTTP method, and optional `headers`, `query`,
  `body` and `json` predicates
- Serves `file:///` Jinja templates as fixtures, with request data in the template
  context
- Renders a `replacement` that contains Jinja delimiters as a template of its own
  (dynamic replacements), e.g. to pick a fixture directory from a header
- Reverse-proxies to the rewritten URL by default, or answers with an HTTP redirect
- Stamps every response, including its own errors, with `X-Mockstack-Result` and
  `X-Mockstack-Rule` headers
- Validates and compiles every rule at startup, so a broken rules file fails fast
- Can simulate resource creation for requests that match no rule
- Provides OpenTelemetry integration for observability

## Configuration

The strategy requires the following configuration:

```python
settings = Settings(
    strategy="proxyrules",
    proxyrules_rules_filename="/path/to/rules.yaml",
    proxyrules_redirect_via="reverse_proxy",  # or "http_307_temporary" or "http_301_permanent"
    proxyrules_reverse_proxy_timeout=10.0,
    proxyrules_simulate_create_on_missing=False,
    proxyrules_verify_ssl_certificates=True,
)
```

Every setting, with its environment variable, is described in
[Configuration](../configuration.md#proxyrules-strategy).

## Rules file

Rules are defined in a YAML file with the following structure:

```yaml
rules:
  - name: user-service
    pattern: ^/api/v1/users/(.*)
    replacement: http://user-service/api/v1/users/\1
    method: GET  # optional, if not specified matches all methods
```

### Rule properties

- `name`: Optional identifier for the rule, used in logs, telemetry and the
  `X-Mockstack-Rule` response header.
- `pattern`: Regular expression matched against the request path with `re.match`, so
  it is anchored at the start of the path. The query string is not part of the path;
  match it with `query`.
- `replacement`: Where the request goes. A URL is reverse-proxied or redirected to; a
  `file:///` path serves a [file template](#file-templates). A plain replacement is
  applied with `re.sub`, so backreferences such as `\1` work. A replacement containing
  `{{`/`{%` is a [dynamic replacement](#dynamic-replacements) instead.
- `method`: Optional HTTP method to match, case-insensitive (if not specified,
  matches all methods, `HEAD` and `OPTIONS` included).
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
  `items.0.name`). Strings are matched raw, without quotes. Every other value is
  re-serialised as a compact JSON literal rather than taken from the request's wire
  text: `true`, `false`, `null`, numbers normalised (`1e2` is matched as `100.0`), and
  objects and arrays with sorted keys and no spaces (`{"a":1,"b":2}`), keeping
  non-ASCII characters as they are. A path that is absent never matches, while a
  present `null` matches as the text `null`. A rule with `body`/`json` never matches a
  request without a body.

Predicate values must be strings. YAML reads unquoted `2`, `true` or `2024` as
numbers and booleans; mockstack converts them back with `str()`, which turns `true`
into `True`, so quote them: `x-api-version: "2"`, `active: "true"`. A predicate with
no value at all (`x-foo:`) is rejected.

!!! tip "Regexes in YAML"
    Write regexes as plain or single-quoted YAML scalars, where a backslash is an
    ordinary character: `replacement: https://projects.example/\1` or
    `query: '(?is).*from\s+sales_facts.*'`. In a double-quoted scalar a backslash
    starts a YAML escape sequence, so `"\1"` and `"\s"` do not parse and must be
    written `"\\1"` and `"\\s"`.

### Matching order

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
      query: '(?is).*FROM\s+sales_facts.*'
    replacement: file:///fixtures/analytics/sales_facts.json.j2
```

The body is read once per request and cached by Starlette, so predicates do not
interfere with reverse proxying or resource-creation simulation.

### Load-time validation

The rules file is loaded, and every rule compiled, when the strategy is constructed at
startup. mockstack refuses to start when the YAML does not parse, and, naming the
offending rule, when:

- a regex (`pattern` or any predicate) is invalid;
- a predicate has no value;
- a Jinja `replacement` has a syntax error;
- a `replacement` mixes Jinja delimiters with a regex backreference (`\1`, `\g<id>`)
  in its literal text;
- a named group in `pattern` shadows a reserved template variable (`path`, `method`,
  `query`, `headers`, `request_json`, `groups`).

A broken rule therefore fails when mockstack starts, not on the first request that
happens to reach it.

## Example rules

Here are some example rules:

```yaml
rules:
  # Redirect all GET requests to /api/v1/users/* to the user service
  - name: user-service-get
    pattern: ^/api/v1/users/(.*)
    replacement: http://user-service/api/v1/users/\1
    method: GET

  # Proxy all POST requests to /api/v1/orders to the order service
  - name: order-service-post
    pattern: ^/api/v1/orders
    replacement: http://order-service/api/v1/orders
    method: POST

  # Redirect all requests to /api/v1/products to the product service
  - name: product-service
    pattern: ^/api/v1/products/(.*)
    replacement: http://product-service/api/v1/products/\1
```

## File templates

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
returns HTTP 200 stamped `X-Mockstack-Result: template`; see
[Error handling](#error-handling) for the failure cases. Use the `tojson` filter to
write request values into JSON fixtures, e.g. `{"id": {{ id | tojson }}}`.

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

## Dynamic replacements

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
is rejected at load; only its literal text is checked, so the same characters inside a
`{{ ... }}` expression or a `{# ... #}` comment are allowed. The URL fragment is not
carried into the rendered result either; only plain `re.sub` mode appends it
(URL-encoded) to the path it rewrites.
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

## Redirection methods

`proxyrules_redirect_via` selects what a rule whose `replacement` is a URL does.
Rules that serve a `file:///` template are unaffected.

1. **Reverse proxy** (`reverse_proxy`, the default; stamped `proxy`)
    - Server forwards the request to the target service
    - Client is unaware of the redirection
    - Useful when you need to work with clients that do not handle HTTP redirects gracefully.
    - Every routed method is forwarded, `HEAD` and `OPTIONS` included, together with
      the query string, headers and body; the `Host` header is set to the target's
      host. The upstream's status, headers and body are returned.
    - Request and response bodies are fully buffered. Hop-by-hop headers
      (`Connection`, `Transfer-Encoding`, `Upgrade`, ..., plus every header named
      in a `Connection` value) are stripped in both directions, and
      `Content-Length` is recomputed for the buffered body, so chunked clients and
      chunked upstreams both work. `1xx`, `204` and `304` responses carry no
      `Content-Length`. A response to `HEAD` keeps the upstream's `Content-Length`,
      unless its `Content-Encoding` names a coding that mockstack decodes (below): that
      length is the encoded one, so it is dropped.
    - Compressed upstream bodies are decoded while they are read: `gzip` and `deflate`
      always, `br` and `zstd` only when the optional `brotli` and `zstandard` packages
      are installed. The decoded codings are removed from `Content-Encoding`, which
      becomes `identity` only when no coding remains. A coding that was not decoded
      (e.g. `compress`) stays in the header, and the body is forwarded still encoded
      with it.
    - The upstream's `Date` and `Server` headers are dropped, so the response carries
      a single `date` and `server` header: the mockstack server's own. Other repeated
      response headers, such as several `Set-Cookie` headers, are passed through one by
      one rather than merged.
    - An upstream that cannot be reached, or does not answer within
      `proxyrules_reverse_proxy_timeout`, is answered by mockstack with a 502 or 504. A
      rewritten URL that cannot be sent at all, such as one that is not an absolute URL,
      is a rules-file mistake and is answered with a 500 (see
      [Error handling](#error-handling)). HTTPS certificates are verified unless
      `proxyrules_verify_ssl_certificates` is disabled.

2. **HTTP Temporary Redirect** (`http_307_temporary`, 307; stamped `redirect`)
    - Client makes a new request to the target URL
    - Preserves the original HTTP method

3. **HTTP Permanent Redirect** (`http_301_permanent`, 301; stamped `redirect`)
    - Client makes a new request to the target URL
    - Browsers may cache the redirect

In both redirect modes the target URL is built from the request path, and the
original query string is then appended to it in the `Location` header: after `?`, or
after `&` when the target already has a query of its own, and before any `#fragment`
of the target. The client's follow-up request goes straight to the target, so its
response carries no `X-Mockstack-*` headers.

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
| `error` | 500 | A fixture failed to render, a template replacement failed, the rewritten URL is not a usable absolute URL, or another internal failure |
| `error` | 502 | The upstream request failed |
| `error` | 504 | The upstream request timed out |

A 404 or 5xx stamped `error` came from mockstack, not from a fixture or the upstream.
Test harnesses should assert on these headers to turn a silently proxied request into
a failure (see the cookbook's
[Asserting in a test suite](../guides/proxyrules-cookbook.md#6-asserting-in-a-test-suite)).
An unstamped 5xx response means the ASGI layer itself failed (outside the strategy),
not that `proxyrules` returned it.

## Error handling

When no matching rule is found, and resource creation simulation is disabled or the
request does not look like a resource creation (see
[Resource creation simulation](#resource-creation-simulation)), the strategy returns a
404 NOT FOUND response stamped `X-Mockstack-Result: missing`, with the configured
`missing_resource_fields` as its body.

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
| The rewritten URL cannot be sent at all: not an absolute URL (e.g. `/api/v1/users`), or an invalid port | 500 | `{"error": "mockstack: internal error"}` |
| Anything else, e.g. a template replacement referencing a missing value, or a malformed JSON body on the resource-creation path | 500 | `{"error": "mockstack: internal error"}` |

The rendered fixture path is never echoed back in a response body; it is only
logged. Upstream failures are logged at WARNING; missing or rejected fixture paths,
and rewritten URLs that cannot be sent, at ERROR; template render failures and
unexpected internal errors at ERROR with a traceback. Log lines name the matched rule.
If the client disconnects before its request body has been read, no response is sent.

A broken rules file fails at startup rather than per request; see
[Load-time validation](#load-time-validation).

## Resource creation simulation

When `proxyrules_simulate_create_on_missing` is enabled, a request that matches no
rule and looks like a resource creation -- a POST whose path does not look like a
search or a command (such as `.../search` or `.../run`), or a request whose path ends
in `/create` -- is answered by simulating the creation instead of a 404:

1. Returning a 201 CREATED status code, stamped `X-Mockstack-Result: create`
2. Echoing back the request body with metadata fields injected into it, when the
   request is JSON (a JSON `Content-Type`, or a path ending in `.json`); any other
   request gets an empty body

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

## OpenTelemetry integration

The strategy automatically adds the following OpenTelemetry attributes when a rule
matches:

- `mockstack.proxyrules.rule_name`: The name of the matched rule (if specified)
- `mockstack.proxyrules.rule_method`: The HTTP method the rule matches (if specified)
- `mockstack.proxyrules.rule_pattern`: The pattern used to match the request
- `mockstack.proxyrules.rule_replacement`: The replacement as written in the rules file
- `mockstack.proxyrules.rewritten_url`: The final URL after applying the rule (proxy
  and redirect results)
- `mockstack.proxyrules.template_path`: The rendered fixture path, and
  `mockstack.proxyrules.result_type` set to `template` (template results)

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
and fixtures for real, and the
[ProxyRules cookbook](../guides/proxyrules-cookbook.md) for smaller recipes of the
same building blocks.

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
  context, and the rule's own `status` and `response_headers`
- Renders a `replacement` that contains Jinja delimiters as a template of its own
  (dynamic replacements), e.g. to pick a fixture directory from a header
- Reverse-proxies to the rewritten URL by default, or answers with an HTTP redirect
- Stamps every response, including its own errors, with `X-Mockstack-Result` and
  `X-Mockstack-Rule` headers
- Validates and compiles every rule at startup, so a broken rules file fails fast
- Can simulate resource creation for requests that match no rule
- Can record real upstream responses into the fixture files its rules serve (record mode)
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
- `status`: Optional HTTP status for the response of a [file template](#file-templates)
  rule, an integer from 200 to 599 (default 200). See
  [Status codes and headers](#status-codes-and-headers).
- `response_headers`: Optional mapping of header name -> value added to the response of
  a file template rule. A list value sends the header once per item.

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
- `status` is not an integer from 200 to 599;
- a `response_headers` entry has an invalid name, no value, or a value that is not a
  string or number, contains a control character, starts or ends with whitespace or is
  not Latin-1, or names a header mockstack manages;
- `status` or `response_headers` is set on a rule whose `replacement` is a plain URL
  rather than a `file:///` fixture;
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
(`project.json.j2` -> `application/json`). A successfully rendered template returns
HTTP 200, or the rule's `status`, stamped `X-Mockstack-Result: template`; see
[Error handling](#error-handling) for the failure cases. Use the `tojson` filter to
write request values into JSON fixtures, e.g. `{"id": {{ id | tojson }}}`.

### Status codes and headers

`status` and `response_headers` set the status and extra headers a fixture is served
with, for example to simulate a dependency that is down:

```yaml
rules:
  - name: orders-outage
    method: GET
    pattern: ^/orders/api/v1/orders/(?P<order_id>[a-z0-9-]+)$
    headers:
      x-test-scenario: outage
    status: 503
    response_headers:
      Retry-After: "30"
    replacement: file:///fixtures/errors/unavailable.json.j2
```

- The response is still stamped `X-Mockstack-Result: template`, so a test can tell a
  fixture's 503 from a 5xx `error` that mockstack itself returned.
- The status and headers apply only once the fixture has rendered. A missing fixture
  or a render failure is answered as described in [Error handling](#error-handling),
  without them.
- A `204` or `304` is sent without a body; the fixture file must still exist.
- Header values are sent as written. A list value sends the header once per item (for
  example several `Set-Cookie` headers), and a `Content-Type` replaces the type
  inferred from the file suffix. As with predicates, quote values that YAML would read
  as numbers or booleans.
- Headers that mockstack manages cannot be set: `Content-Length`, the hop-by-hop
  headers (`Connection`, `Keep-Alive`, `Proxy-Authenticate`, `Proxy-Authorization`,
  `TE`, `Trailer`, `Transfer-Encoding`, `Upgrade`), `Date`, `Server`, and the
  `X-Mockstack-Result` and `X-Mockstack-Rule` result headers.
- Only fixture rules can set them. A rule whose plain `replacement` is a URL is
  rejected at startup; a [dynamic replacement](#dynamic-replacements) is only known per
  request, so one that renders a URL is answered with a 500 stamped `error`.

The cookbook recipe
[Fixture status codes and headers](../guides/proxyrules-cookbook.md#8-fixture-status-codes-and-headers)
shows a 503, a 429 with `application/problem+json`, and a 201 with `Location`.

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

## Recording fixtures

Record mode fills in fixtures from the real service. When a fixture rule matches and its
file does not exist yet, mockstack sends the request to the next matching rule whose
`replacement` is a URL, writes the response body to the fixture file, and answers by
rendering that file, stamped `X-Mockstack-Result: record`. Later requests are served from
the file, stamped `template`, without calling the service. Existing rules files work
unchanged: the passthrough rule that follows a fixture rule is where it records from.
Later rules whose `replacement` is a plain `file:///` path are skipped when looking for it.

```yaml
rules:
  - name: users-fixture
    method: GET
    pattern: ^/users/api/v1/users/(?P<user_id>[a-z0-9-]+)$
    headers:
      x-test-scenario: "[a-z0-9_-]+"
    replacement: file:///srv/fixtures/{{ headers['x-test-scenario'] }}/users/{{ user_id }}.json.j2

  - name: users-passthrough
    pattern: ^/users/(.*)
    replacement: https://users.example/\1
```

Start mockstack with `MOCKSTACK__PROXYRULES_RECORD_MODE=missing` and
`MOCKSTACK__PROXYRULES_RECORD_ROOT=/srv/fixtures`, run the traffic you want fixtures for,
then review and commit the recorded files and run without record mode.

| `proxyrules_record_mode` | Behaviour |
| --- | --- |
| `off` (default) | Fixtures are only served |
| `missing` | A fixture file that does not exist yet is recorded |
| `overwrite` | Files recorded before are recorded again, e.g. to refresh stale fixtures; hand-written fixtures are never overwritten |

A response is recorded only when:

- a later matching rule has a URL `replacement`;
- the request is not a `HEAD` or `OPTIONS`;
- the upstream's status equals the fixture rule's `status` (200 by default), so the
  fixture replays with the status it was recorded with;
- the body is UTF-8 text;
- the body is not still compressed with a coding mockstack does not decode (for example
  `br` without the optional `brotli` package); `gzip` and `deflate` bodies are recorded
  decoded.

Otherwise the upstream's response is returned stamped `proxy` with the URL rule's name,
and the reason is logged -- at INFO for a `HEAD`/`OPTIONS` request or a scrubber that
returns `None`, since both are expected; every other reason is logged at WARNING. With
no later URL rule, a missing fixture is
the usual 404 `error`. An upstream that fails is the usual 502 or 504 `error`, and a
fixture file that cannot be written is a 500 `error`; nothing is written in either case.

A later rule's `replacement` is still rendered even when it is a
[dynamic replacement](#dynamic-replacements), to learn whether it gives a URL at all --
so a later template replacement that fails (for example one that references a missing
header) turns that record attempt into a 500, the same as it would for a plain proxied
request to that rule.

Recorded files:

- start with `{# mockstack:recorded #}`, which renders to nothing and is how `overwrite`
  tells them from hand-written fixtures;
- contain the body exactly: any Jinja syntax or carriage return in it is printed by an
  expression, so it is never evaluated and replays byte for byte;
- are written to a temporary file and renamed into place, so concurrent requests never
  read a partial fixture;
- must resolve, symlinks followed, inside `proxyrules_record_root`. A fixture path
  outside it is served as usual and not recorded, with a warning the first time for each
  rule.

While a fixture has not been recorded yet:

- requests really reach the upstream, including non-idempotent methods such as `POST`,
  `PUT` and `DELETE` -- recording a create endpoint creates real resources there;
- a response that cannot be recorded (a status mismatch, a still-encoded or non-UTF-8
  body, or a scrubber that returns `None`) is sent to the upstream again on every
  request, not only the first;
- there is no locking between requests: concurrent first requests for the same fixture
  each reach the upstream, and the last write to complete wins. A reader never sees a
  partial file, but overlapping requests can each record a different upstream response;
- `HEAD` and `OPTIONS` requests for a fixture that may still be recorded are proxied
  rather than served from a fixture file; in `overwrite` mode this also applies to a
  fixture that was already recorded.

Only the response body is recorded. The rule's `status` and `response_headers` apply when
it is replayed, and the content type follows the file suffix as for any fixture.

### Scrubbing recorded bodies

`proxyrules_record_scrubber` names a `module:function` that is called with every body
before it is written. It returns the text to write, or `None` to skip recording that
response, which is then returned stamped `proxy`:

```python
def mask_emails(body: str, *, request: Request, rule_name: str | None, path: Path) -> str | None:
    return EMAIL.sub("***@***", body)
```

The reference is imported and checked when the settings are loaded, so a typo or a
target that is not callable stops mockstack from starting; the module must be
importable, e.g. with `PYTHONPATH=.`. A scrubber that raises, or returns something
other than a string or `None`, answers that request with a 500 `error` and nothing is
written. `rule_name` is the matched fixture rule's `name` (`None` when the rule has
none), and `path` is the resolved fixture file path that will be written.

The scrubber must be a regular synchronous function, not `async def`: it is called
directly, not awaited, so an `async def` scrubber returns a coroutine object rather
than a string, and the request gets a 500 the same as any other non-`str`, non-`None`
return value. See the cookbook's
[Record fixtures from a real service](../guides/proxyrules-cookbook.md#9-record-fixtures-from-a-real-service).

!!! warning
    Record mode writes files whose paths can be chosen by request data and whose content
    comes from the upstream. Enable it only for a recording session on a trusted
    network, never on a shared or exposed instance, and review recorded fixtures before
    committing them: they contain whatever the real service returned. A test harness
    that asserts `X-Mockstack-Result: template` fails on `record`, so a gating run that
    accidentally records is caught.

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
| `X-Mockstack-Result` | `template`, `proxy`, `redirect`, `create`, `missing`, `record` or `error` |
| `X-Mockstack-Rule` | The matched rule's `name` (or its `pattern` when unnamed); absent when no rule matched |

| `X-Mockstack-Result` | Status | Meaning |
| --- | --- | --- |
| `template` | 200, or the rule's `status` | A `file:///` fixture was rendered |
| `record` | The rule's `status` (200 by default) | Record mode wrote the upstream response to the fixture file and served it from that file |
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
matches. The shared rule attributes (`rule_name`, `rule_method`, `rule_pattern`,
`rule_replacement`) always describe the rule named in the response's
`X-Mockstack-Rule` header, never some other rule that was merely consulted along the
way (e.g. a record-mode upstream rule whose response ends up recorded and replayed
from the fixture instead):

- `mockstack.proxyrules.rule_name`: The name of the matched rule (if specified)
- `mockstack.proxyrules.rule_method`: The HTTP method the rule matches (if specified)
- `mockstack.proxyrules.rule_pattern`: The pattern used to match the request
- `mockstack.proxyrules.rule_replacement`: The replacement as written in the rules file
- `mockstack.proxyrules.rewritten_url`: The final URL after applying the rule (proxy
  and redirect results)
- `mockstack.proxyrules.result_type`: The result type stamped on the response (`proxy`,
  `redirect`, `template`, `error`, or in record mode `record`), set on every proxy,
  redirect, template and error result
- `mockstack.proxyrules.template_path`: The rendered fixture path (template results)

An error response that names a rule (`X-Mockstack-Result: error` with an
`X-Mockstack-Rule` header -- e.g. a missing or unrenderable fixture, an unreachable
upstream, or a record-mode write failure) carries that rule's shared attributes and
`result_type` `error`, overwriting any result type an earlier, now-superseded call had
set for the same response (e.g. a reverse proxy attempt that set `proxy` before it
failed).

In record mode (`proxyrules_record_mode`), attempting to record from the next matching
URL rule also sets:

- `mockstack.proxyrules.upstream_rule_name`: The name (or pattern, when unnamed) of the
  rule the request was proxied to while attempting to record
- `mockstack.proxyrules.recorded_path`: The fixture path written, when the response was
  recorded (`result_type` is `record`; the shared rule attributes describe the fixture
  rule)
- `mockstack.proxyrules.not_recorded_reason`: Why the response was not recorded, when it
  was not (`result_type` is `proxy`; the shared rule attributes describe the upstream
  rule, since that is what `X-Mockstack-Rule` names)

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

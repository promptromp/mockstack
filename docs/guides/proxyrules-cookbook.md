# ProxyRules cookbook

Recipes for common [`proxyrules`](../strategies/proxyrules.md) setups. Each recipe's
rules file and fixtures below are the real files in
[`examples/proxyrules-cookbook/`](https://github.com/promptromp/mockstack/tree/main/examples/proxyrules-cookbook),
and `mockstack/tests/live/test_cookbook.py` runs every `curl` command on this page
against a live mockstack, so the responses shown are the responses you get.

## Running the recipes

The [cookbook README](https://github.com/promptromp/mockstack/tree/main/examples/proxyrules-cookbook)
has the one-time setup. In short: start the echo "real service" in one terminal, then,
from a recipe's directory, fill in the rules file's placeholders and start mockstack:

```bash
uv run python ../upstream.py   # echo upstream on 127.0.0.1:8081, in its own terminal

export FIXTURES_DIR="$PWD/fixtures" UPSTREAM_URL=http://127.0.0.1:8081
envsubst '${FIXTURES_DIR} ${UPSTREAM_URL}' < rules.yml > rules.local.yml
MOCKSTACK__STRATEGY=proxyrules MOCKSTACK__PROXYRULES_RULES_FILENAME=rules.local.yml uv run mockstack
```

Under each command, the comment lines show the status line, the `X-Mockstack-Result`
and `X-Mockstack-Rule` response headers and the body. `curl -i` prints a few more
headers (`date`, `content-length`, ...) that are left out here, and a `...` stands for
the rest of a long body.

## 1. Serve fixtures to tagged test traffic

Put a narrow rule with a header predicate ahead of a broad passthrough for the same
path prefix. Rules are tried in order and the first match wins, so tagged requests get
the fixture, and every other request is reverse-proxied to the real service unchanged:
untagged requests, and tagged requests to endpoints that have no fixture rule.

```yaml title="01-tagged-traffic/rules.yml"
--8<-- "examples/proxyrules-cookbook/01-tagged-traffic/rules.yml"
```

```jinja title="01-tagged-traffic/fixtures/projects/project.json.j2"
--8<-- "examples/proxyrules-cookbook/01-tagged-traffic/fixtures/projects/project.json.j2"
```

The fixture can use the named group `id` from `pattern` and the request `headers`
(names lower-cased); see [Template context](../strategies/proxyrules.md#template-context)
for everything available.

```bash
curl -i -H "X-Test-Run: ci-42" http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: projects-fixture
# {"id": "proj-123", "name": "Test project", "status": "ACTIVE", "test_run": "ci-42"}

curl -i http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: projects-passthrough
# {"source":"upstream","path":"/api/v1/project/proj-123","method":"GET",...}

curl -i -H "X-Test-Run: ci-42" "http://127.0.0.1:8000/projects/api/v1/projects?page=2"
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: projects-passthrough
# {"source":"upstream","path":"/api/v1/projects","method":"GET","query":{"page":"2"},...}
```

## 2. Per-scenario fixture directories

A `replacement` containing `{{ ... }}` is rendered with Jinja, so a request header can
choose the fixture directory. Restrict the header predicate to the characters a
directory name needs: a value outside that class fails the predicate and falls through
to the passthrough. A value that passes the predicate but has no fixture directory is
*not* passed through: the rule still matched, so the request is answered 404 and
stamped `error`, and a typo'd scenario never reaches the real service.

```yaml title="02-scenario-directories/rules.yml"
--8<-- "examples/proxyrules-cookbook/02-scenario-directories/rules.yml"
```

```jinja title="02-scenario-directories/fixtures/healthy/projects/project.json.j2"
--8<-- "examples/proxyrules-cookbook/02-scenario-directories/fixtures/healthy/projects/project.json.j2"
```

```jinja title="02-scenario-directories/fixtures/archived/projects/project.json.j2"
--8<-- "examples/proxyrules-cookbook/02-scenario-directories/fixtures/archived/projects/project.json.j2"
```

```bash
curl -i -H "X-Test-Scenario: healthy" http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: projects-scenario
# {"id": "proj-123", "status": "ACTIVE", "scenario": "healthy"}

curl -i -H "X-Test-Scenario: archived" http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: projects-scenario
# {"id": "proj-123", "status": "ARCHIVED", "scenario": "archived"}

curl -i -H "X-Test-Scenario: flaky" http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 404 Not Found
# x-mockstack-result: error
# x-mockstack-rule: projects-scenario
# {"error":"Template file not found."}

curl -i -H "X-Test-Scenario: Healthy" http://127.0.0.1:8000/projects/api/v1/project/proj-123
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: projects-passthrough
# {"source":"upstream","path":"/api/v1/project/proj-123","method":"GET",...}
```

!!! warning
    Never let an unconstrained request value build a fixture path or an upstream URL.
    mockstack rejects a rendered path containing `..`, but a `.*` predicate would still
    let the header pick any file *within* the fixture tree. See the warning under
    [Dynamic replacements](../strategies/proxyrules.md#dynamic-replacements).

## 3. Mock a single-endpoint API by request body

SQL gateways and RPC-style APIs send every request to one path and put the intent in
the body. A `json:` predicate maps a dotted path in the JSON body to a regex that must
match the whole value. Here `(?is)` makes the match case-insensitive and lets `.`
cross the line breaks of multi-line SQL; single-quoted YAML keeps the backslashes of
`\b` and `\s` as they are. The fixture receives the parsed body as `request_json`,
and the `tojson` filter writes it back as valid JSON.

```yaml title="03-sql-gateway/rules.yml"
--8<-- "examples/proxyrules-cookbook/03-sql-gateway/rules.yml"
```

```jinja title="03-sql-gateway/fixtures/analytics/sales_facts.json.j2"
--8<-- "examples/proxyrules-cookbook/03-sql-gateway/fixtures/analytics/sales_facts.json.j2"
```

```bash
curl -i -H "Content-Type: application/json" \
  -d '{"query": "SELECT region, SUM(amount) AS total FROM sales_facts GROUP BY region"}' \
  http://127.0.0.1:8000/analytics/v1/sql
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: sales-facts-query
# {"columns": ["region", "total"], "rows": [["north", 1250.0], ["south", 980.5]], "request": {"query": "SELECT region, SUM(amount) AS total FROM sales_facts GROUP BY region"}}

curl -i -H "Content-Type: application/json" \
  -d '{"query": "SELECT id FROM orders LIMIT 10"}' \
  http://127.0.0.1:8000/analytics/v1/sql
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: analytics-passthrough
# {"source":"upstream","path":"/v1/sql","method":"POST",...}
```

## 4. Match JSON literals

A `json:` predicate is matched against the JSON *text form* of the value at its path.
Strings are matched as they are, without quotes. Every other value is re-serialised as
compact JSON, not taken from the request's wire text: `true`, `false`, `null`,
numbers as Python's `json` writes them, and objects and arrays with sorted keys and no
spaces. Quote predicate values in YAML (`"true"`, `"50"`) so they stay strings.

```yaml title="04-json-literals/rules.yml"
--8<-- "examples/proxyrules-cookbook/04-json-literals/rules.yml"
```

```jinja title="04-json-literals/fixtures/orders/search.json.j2"
--8<-- "examples/proxyrules-cookbook/04-json-literals/fixtures/orders/search.json.j2"
```

All rules share one path, so `X-Mockstack-Rule` tells which predicate matched:

```bash
curl -i -H "Content-Type: application/json" -d '{"filter": {"express": true}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: express-orders
# {"orders": [{"id": "ord-1001", "status": "OPEN"}], "total": 1}

curl -i -H "Content-Type: application/json" -d '{"filter": {"express": "true"}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: express-orders

curl -i -H "Content-Type: application/json" -d '{"filter": {"assignee": null}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: unassigned-orders

curl -i -H "Content-Type: application/json" -d '{"filter": {"status": "OPEN"}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: orders-passthrough

curl -i -H "Content-Type: application/json" -d '{"page": {"number": 1, "size": 50}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: page-size-50

curl -i -H "Content-Type: application/json" -d '{"page": {"number": 1, "size": 5e1}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: orders-passthrough

curl -i -H "Content-Type: application/json" -d '{"filter": {"customer": {"tier": "gold", "id": 42}}}' http://127.0.0.1:8000/orders/api/v1/search
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: gold-customer
```

What these show:

- **Booleans:** `"true"` matches the JSON boolean `true`, and also the string `"true"`,
  because strings are matched without their quotes.
- **`null` versus absent:** `"null"` matches a present `null`. A path that is absent
  never matches, whatever the regex, so `{"filter": {"status": "OPEN"}}` falls through.
- **Numbers:** `"50"` matches `50`. Numbers are re-serialised, so `5e1` is matched as
  `50.0` and does not match. Use a regex such as `"50(\\.0)?"` to accept both forms.
- **Objects:** `{"tier": "gold", "id": 42}` is matched as `{"id":42,"tier":"gold"}`,
  whatever the key order and spacing of the request.

## 5. Query-parameter predicates

`pattern` is matched against the request path only; the query string never reaches it.
Match query parameters with `query:` predicates instead, each a regex that must match
the parameter's whole value. When a parameter is repeated, mockstack uses its *last*
value, both for predicates and for `query` in templates.

```yaml title="05-query-parameters/rules.yml"
--8<-- "examples/proxyrules-cookbook/05-query-parameters/rules.yml"
```

```jinja title="05-query-parameters/fixtures/users/page.json.j2"
--8<-- "examples/proxyrules-cookbook/05-query-parameters/fixtures/users/page.json.j2"
```

```jinja title="05-query-parameters/fixtures/users/archived.json.j2"
--8<-- "examples/proxyrules-cookbook/05-query-parameters/fixtures/users/archived.json.j2"
```

```bash
curl -i "http://127.0.0.1:8000/users/api/v1/users?page=2"
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: users-page
# {"page": 2, "per_page": 2, "users": ["user-1", "user-2"]}

curl -i "http://127.0.0.1:8000/users/api/v1/users?status=archived&page=2"
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: archived-users
# {"status": "archived", "users": ["user-9"]}

curl -i "http://127.0.0.1:8000/users/api/v1/users?status=active&status=archived"
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: archived-users
# {"status": "archived", "users": ["user-9"]}

curl -i "http://127.0.0.1:8000/users/api/v1/users?status=archived&status=active"
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: users-passthrough
# {"source":"upstream","path":"/api/v1/users","method":"GET",...}
```

The second request satisfies both fixture rules; the first rule in the file wins.

## 6. Asserting in a test suite

A passthrough rule is a safety net for real traffic, but in a test suite it can hide a
broken fixture rule: if a path or header changes, the request silently reaches the real
service and the test may still pass. Assert `X-Mockstack-Result` on every response
that should come from a fixture:

<!-- fmt: off -->
```python title="06-asserting-in-tests/fixture_assertions.py"
--8<-- "examples/proxyrules-cookbook/06-asserting-in-tests/fixture_assertions.py"
```
<!-- fmt: on -->

Run it against mockstack started on this recipe's rules:

```bash
MOCKSTACK_URL=http://127.0.0.1:8000 uv run pytest fixture_assertions.py
```

If the fixture rule stops matching, the request is proxied and `expect_fixture` fails
with a message like `GET /projects/api/v1/project/proj-123 got 200 with
X-Mockstack-Result='proxy' (rule 'projects-passthrough'), not a fixture`.

### Reading error results

When a failure is mockstack's own, the response is stamped `X-Mockstack-Result: error`
(plus `X-Mockstack-Rule` for the rule that matched) with a JSON `error` message. The
details, such as the rendered path or the exception, are only in mockstack's log.

| Status | Body | Meaning |
| --- | --- | --- |
| 404 | `{"error":"Template file not found."}` | A rule matched, but the fixture file it rendered does not exist (or its path contains `..`) |
| 500 | `{"error":"An internal error occurred while rendering the template."}` | The fixture file failed to render |
| 500 | `{"error":"mockstack: internal error"}` | Any other failure, such as a `replacement` that references an undefined value or does not produce an absolute URL |
| 502 | `{"error":"mockstack: upstream request failed"}` | The upstream could not be reached, or broke the connection or protocol |
| 504 | `{"error":"mockstack: upstream request timed out"}` | The upstream did not answer within `proxyrules_reverse_proxy_timeout` |

A request that matches no rule at all is a different case: it is answered 404 stamped
`X-Mockstack-Result: missing`, with no `X-Mockstack-Rule`.

The rest of this recipe's rules file has one rule for each error. Start mockstack with
`MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT=1` so the slow upstream times out:

```jinja title="06-asserting-in-tests/fixtures/orders/echo.json.j2"
--8<-- "examples/proxyrules-cookbook/06-asserting-in-tests/fixtures/orders/echo.json.j2"
```

```yaml title="06-asserting-in-tests/rules.yml"
--8<-- "examples/proxyrules-cookbook/06-asserting-in-tests/rules.yml"
```

```jinja title="06-asserting-in-tests/fixtures/projects/project.json.j2"
--8<-- "examples/proxyrules-cookbook/06-asserting-in-tests/fixtures/projects/project.json.j2"
```

```jinja title="06-asserting-in-tests/fixtures/users/user-1.json.j2"
--8<-- "examples/proxyrules-cookbook/06-asserting-in-tests/fixtures/users/user-1.json.j2"
```

```bash
curl -i http://127.0.0.1:8000/users/api/v1/users/user-2
# HTTP/1.1 404 Not Found
# x-mockstack-result: error
# x-mockstack-rule: user-fixture
# {"error":"Template file not found."}

curl -i http://127.0.0.1:8000/tenants/tenant-a/projects
# HTTP/1.1 500 Internal Server Error
# x-mockstack-result: error
# x-mockstack-rule: tenant-projects
# {"error":"mockstack: internal error"}

curl -i http://127.0.0.1:8000/orders/api/v1/echo
# HTTP/1.1 500 Internal Server Error
# x-mockstack-result: error
# x-mockstack-rule: order-echo
# {"error":"An internal error occurred while rendering the template."}

curl -i http://127.0.0.1:8000/accounts/v1/balance
# HTTP/1.1 500 Internal Server Error
# x-mockstack-result: error
# x-mockstack-rule: accounts-relative
# {"error":"mockstack: internal error"}

curl -i http://127.0.0.1:8000/invoices/api/v1/invoices
# HTTP/1.1 502 Bad Gateway
# x-mockstack-result: error
# x-mockstack-rule: invoices-unreachable
# {"error":"mockstack: upstream request failed"}

curl -i http://127.0.0.1:8000/reports/daily
# HTTP/1.1 504 Gateway Timeout
# x-mockstack-result: error
# x-mockstack-rule: reports-slow
# {"error":"mockstack: upstream request timed out"}
```

## 7. Redirect mode versus reverse proxy

By default a rule whose `replacement` is a URL reverse-proxies the request: mockstack
calls the upstream and returns its response, stamped `proxy`. With
`proxyrules_redirect_via=http_307_temporary` (or `http_301_permanent`) mockstack
instead answers with a redirect to the rewritten URL, stamped `redirect`, and the client
makes the upstream call itself. File fixture rules are served the same way in both
modes. Start mockstack with `MOCKSTACK__PROXYRULES_REDIRECT_VIA=http_307_temporary`:

```yaml title="07-redirect-mode/rules.yml"
--8<-- "examples/proxyrules-cookbook/07-redirect-mode/rules.yml"
```

```jinja title="07-redirect-mode/fixtures/users/user-1.json.j2"
--8<-- "examples/proxyrules-cookbook/07-redirect-mode/fixtures/users/user-1.json.j2"
```

```bash
curl -i http://127.0.0.1:8000/users/api/v1/users/user-1
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: user-fixture
# {"id": "user-1", "name": "Test user"}

curl -i http://127.0.0.1:8000/users/api/v1/users/user-2
# HTTP/1.1 307 Temporary Redirect
# location: http://127.0.0.1:8081/api/v1/users/user-2
# x-mockstack-result: redirect
# x-mockstack-rule: users-redirect

curl -i -L http://127.0.0.1:8000/users/api/v1/users/user-2
# HTTP/1.1 307 Temporary Redirect
# location: http://127.0.0.1:8081/api/v1/users/user-2
# x-mockstack-result: redirect
# x-mockstack-rule: users-redirect
#
# HTTP/1.1 200 OK
# {"source":"upstream","path":"/api/v1/users/user-2","method":"GET",...}

curl -i "http://127.0.0.1:8000/users/api/v1/users?page=2"
# HTTP/1.1 307 Temporary Redirect
# location: http://127.0.0.1:8081/api/v1/users?page=2
# x-mockstack-result: redirect
# x-mockstack-rule: users-redirect
```

Things to know before choosing redirect mode:

- The final response comes straight from the upstream, so it carries no
  `X-Mockstack-*` headers, and a test cannot tell from it that mockstack was involved.
- The client must be able to reach the upstream itself, and must follow redirects.
- The original query string is kept: it is appended to the rewritten URL in
  `location` (with `&` if the replacement already has a query of its own).

## 8. Fixture status codes and headers

A fixture is answered with HTTP 200 unless its rule sets `status`, which makes it easy to
test how a client handles a dependency that is down, throttled, or answers with a
non-200 success. `response_headers` adds headers such as `Retry-After` or `Location`; a
list value sends a header once per item, and a `Content-Type` replaces the type inferred
from the file suffix. The response is still stamped `X-Mockstack-Result: template`: the
status came from your fixture, so `error` keeps meaning that mockstack itself failed.

```yaml title="08-status-and-headers/rules.yml"
--8<-- "examples/proxyrules-cookbook/08-status-and-headers/rules.yml"
```

```jinja title="08-status-and-headers/fixtures/errors/unavailable.json.j2"
--8<-- "examples/proxyrules-cookbook/08-status-and-headers/fixtures/errors/unavailable.json.j2"
```

```jinja title="08-status-and-headers/fixtures/errors/rate-limited.json.j2"
--8<-- "examples/proxyrules-cookbook/08-status-and-headers/fixtures/errors/rate-limited.json.j2"
```

```jinja title="08-status-and-headers/fixtures/orders/created.json.j2"
--8<-- "examples/proxyrules-cookbook/08-status-and-headers/fixtures/orders/created.json.j2"
```

```bash
curl -i -H "X-Test-Scenario: outage" http://127.0.0.1:8000/orders/api/v1/orders/ord-1001
# HTTP/1.1 503 Service Unavailable
# retry-after: 30
# x-mockstack-result: template
# x-mockstack-rule: orders-outage
# {"error": "service unavailable", "order_id": "ord-1001"}

curl -i -H "X-Test-Scenario: throttled" http://127.0.0.1:8000/orders/api/v1/orders/ord-1001
# HTTP/1.1 429 Too Many Requests
# content-type: application/problem+json
# retry-after: 5
# x-mockstack-result: template
# x-mockstack-rule: orders-rate-limited
# {"type": "about:blank", "title": "Too Many Requests", "status": 429}

curl -i -H "Content-Type: application/json" -d '{"customer": "cust-7"}' http://127.0.0.1:8000/orders/api/v1/orders
# HTTP/1.1 201 Created
# location: /orders/api/v1/orders/ord-1001
# x-mockstack-result: template
# x-mockstack-rule: order-created
# {"id": "ord-1001", "status": "OPEN", "customer": "cust-7"}

curl -i http://127.0.0.1:8000/orders/api/v1/orders/ord-1001
# HTTP/1.1 200 OK
# x-mockstack-result: proxy
# x-mockstack-rule: orders-passthrough
# {"source":"upstream","path":"/api/v1/orders/ord-1001","method":"GET",...}
```

Things to know:

- The status and headers apply only once the fixture has rendered. A missing fixture is
  still a 404 stamped `error`, without them.
- A `204` or `304` is sent without a body, but its fixture file must still exist.
- `status` and `response_headers` only work on `file:///` fixture rules: mockstack
  refuses to start when a rule whose `replacement` is a URL sets them.
- Headers that mockstack manages cannot be set: `Content-Length`, hop-by-hop headers
  such as `Connection` and `Transfer-Encoding`, `Date`, `Server` and the
  `X-Mockstack-*` result headers.

## 9. Record fixtures from a real service

Instead of writing fixtures by hand, let mockstack record them. In record mode, a fixture
rule whose file does not exist yet sends the request on to the next matching URL rule,
writes the response into the fixture file, and answers from that file. A scrubber can
rewrite each body before it is written, here to mask e-mail addresses. Start mockstack
from the recipe directory:

```bash
mkdir -p fixtures
PYTHONPATH=. MOCKSTACK__STRATEGY=proxyrules MOCKSTACK__PROXYRULES_RULES_FILENAME=rules.local.yml \
  MOCKSTACK__PROXYRULES_RECORD_MODE=missing MOCKSTACK__PROXYRULES_RECORD_ROOT=fixtures \
  MOCKSTACK__PROXYRULES_RECORD_SCRUBBER=scrubbers:mask_emails uv run mockstack
```

```yaml title="09-recording/rules.yml"
--8<-- "examples/proxyrules-cookbook/09-recording/rules.yml"
```

<!-- fmt: off -->
```python title="09-recording/scrubbers.py"
--8<-- "examples/proxyrules-cookbook/09-recording/scrubbers.py"
```
<!-- fmt: on -->

The first request is recorded from the echo upstream, with the address masked:

```bash
curl -i "http://127.0.0.1:8000/users/api/v1/users/user-7?contact=ada@example.com"
# HTTP/1.1 200 OK
# x-mockstack-result: record
# x-mockstack-rule: users-recorded
# {"source":"upstream","path":"/api/v1/users/user-7","method":"GET","query":{"contact":"***@***"},...}
```

`fixtures/users/user-7.json.j2` now holds that body, after a `{# mockstack:recorded #}`
marker. The same request is then served from the file, without calling the upstream:

```bash
curl -i "http://127.0.0.1:8000/users/api/v1/users/user-7?contact=ada@example.com"
# HTTP/1.1 200 OK
# x-mockstack-result: template
# x-mockstack-rule: users-recorded
# {"source":"upstream","path":"/api/v1/users/user-7","method":"GET","query":{"contact":"***@***"},...}
```

Things to know:

- Restart without the three `RECORD` settings to replay only. `overwrite` mode re-records
  files carrying the marker and never touches hand-written fixtures.
- A response is recorded only when its status matches the rule's `status` (200 by
  default) and its body is text; otherwise it is returned stamped `proxy`. See
  [Recording fixtures](../strategies/proxyrules.md#recording-fixtures).
- Recorded files contain whatever the real service returned. Review them before
  committing, and never run record mode on a shared or exposed instance.

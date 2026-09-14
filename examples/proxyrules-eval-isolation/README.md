# proxyrules eval isolation

This example shows the eval-isolation pattern: requests carrying an
`X-Request-Eval-Scenario` header are served from per-scenario fixtures, while
everything else fails open and is reverse-proxied to the real service. One
mockstack instance can therefore sit in front of production traffic and serve
deterministic fixtures only to stamped evaluation traffic.

The pattern in `rules.yml`, evaluated top to bottom (first match wins):

1. A narrow, header-gated rule matches stamped requests and renders a
   `file:///` Jinja template from `fixtures/<scenario>/...`.
2. A broad passthrough rule matches everything else on that path prefix and
   reverse-proxies it to the real service, unchanged.

The `x-request-eval-scenario` predicate is restricted to `[a-z0-9_-]+` (not
`.*`) so the header can only select a sibling scenario directory under
`fixtures/`, never escape it -- see the warning under "Dynamic replacements" in
[`docs/strategies/proxyrules.md`](../../docs/strategies/proxyrules.md).

Assert on `X-Mockstack-Result`/`X-Mockstack-Rule` in your eval harness so a
rule that silently stops matching (and falls through to the real service)
fails the run instead of passing quietly.

## Run it

In one terminal, start the demo "real service":

```bash
python upstream.py
```

In another, render the rules file (mockstack does not expand `${VAR}`
placeholders itself) and start mockstack. `envsubst` ships with GNU gettext;
on macOS install it with `brew install gettext` if it's missing, or use any
equivalent `${VAR}` substitution tool instead:

```bash
export FIXTURES_DIR=$(pwd)/fixtures PROJECTS_URL=http://127.0.0.1:8081 ANALYTICS_URL=http://127.0.0.1:8081
envsubst < rules.yml > rules.local.yml

MOCKSTACK__STRATEGY=proxyrules MOCKSTACK__PROXYRULES_RULES_FILENAME=rules.local.yml uvx mockstack
# or: uv run mockstack
```

Instead of passing `MOCKSTACK__*` variables inline, you can copy
`.env.example` to `.env` (as in `examples/proxyrules-with-rules-file`) --
its `MOCKSTACK__PROXYRULES_RULES_FILENAME` already points at
`./rules.local.yml`, matching the command above -- and just run
`uvx mockstack` / `uv run mockstack`.

Then, in a third terminal:

```bash
# 1. Stamped GET -> served from fixtures/healthy/projects/project.json.j2
curl -i -H "X-Request-Eval-Scenario: healthy" \
  http://127.0.0.1:8000/projects/api/v1/project/proj-123
# X-Mockstack-Result: template
# X-Mockstack-Rule: projects-eval

# 2. Unstamped GET -> reverse-proxied to upstream.py
curl -i http://127.0.0.1:8000/projects/api/v1/project/proj-123
# X-Mockstack-Result: proxy
# X-Mockstack-Rule: projects-passthrough

# 3. Stamped analytics POST mentioning sales_facts -> served from fixtures
curl -i -H "X-Request-Eval-Scenario: healthy" -H "Content-Type: application/json" \
  -d '{"query": "SELECT region FROM sales_facts WHERE 1=1"}' \
  http://127.0.0.1:8000/analytics/v1/sql
# X-Mockstack-Result: template
# X-Mockstack-Rule: analytics-sales-eval
```

`mockstack/tests/live/test_example_eval_isolation.py` runs these same three
scenarios (plus a fourth: a stamped analytics query that does *not* mention
`sales_facts`, which falls through to the passthrough rule) against this
example's real `rules.yml` and fixtures, so the example can't drift from what
is tested.

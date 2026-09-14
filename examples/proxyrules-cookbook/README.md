# proxyrules cookbook

Runnable files for the recipes on the
[ProxyRules cookbook](https://promptromp.github.io/mockstack/guides/proxyrules-cookbook/)
docs page. Each numbered directory holds one recipe's `rules.yml` and `fixtures/`:

| Directory | Recipe |
| --- | --- |
| `01-tagged-traffic` | Serve fixtures to tagged test traffic, pass everything else through |
| `02-scenario-directories` | Per-scenario fixture directories selected by a header |
| `03-sql-gateway` | Mock a single-endpoint API by request body |
| `04-json-literals` | Match JSON literals: booleans, `null`, numbers, objects |
| `05-query-parameters` | Query-parameter predicates |
| `06-asserting-in-tests` | Asserting in a test suite, and reading error results |
| `07-redirect-mode` | Redirect mode versus reverse proxy |

`mockstack/tests/live/test_cookbook.py` loads these exact files and runs every `curl`
command from the docs page against them, so the files and the page cannot drift.

## One-time setup

From a clone of the repository, install the project (`uv sync`), then start the echo
"real service" in its own terminal. It answers every request with what it received,
and `GET /slow` waits three seconds first:

```bash
cd examples/proxyrules-cookbook
uv run python upstream.py        # listens on 127.0.0.1:8081; pass a port to change it
```

The rules files contain `${FIXTURES_DIR}` and `${UPSTREAM_URL}` placeholders, which
mockstack does not expand itself. `envsubst` (GNU gettext; `brew install gettext` on
macOS) fills them in. Name the two variables so no other `$` in a regex is touched.

## Run a recipe

In a second terminal, from the recipe's directory:

```bash
cd examples/proxyrules-cookbook/01-tagged-traffic
export FIXTURES_DIR="$PWD/fixtures" UPSTREAM_URL=http://127.0.0.1:8081
envsubst '${FIXTURES_DIR} ${UPSTREAM_URL}' < rules.yml > rules.local.yml
MOCKSTACK__STRATEGY=proxyrules MOCKSTACK__PROXYRULES_RULES_FILENAME=rules.local.yml uv run mockstack
```

Two recipes need one more setting on the last line:

- `06-asserting-in-tests`: `MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT=1`, so the
  slow upstream times out.
- `07-redirect-mode`: `MOCKSTACK__PROXYRULES_REDIRECT_VIA=http_307_temporary`.

Then, in a third terminal, run the recipe's `curl` commands from the docs page.
mockstack listens on `127.0.0.1:8000`. Stop it with Ctrl-C before starting the
next recipe.

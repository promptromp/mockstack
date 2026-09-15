# CLAUDE.md

Guidance for AI coding agents and contributors working in this repository.

## What mockstack is

mockstack is an API-mocking service built on FastAPI. A catch-all route hands every
request to one *strategy*, selected with the `strategy` setting:

- `filefixtures`: renders Jinja templates from `templates_dir`, chosen from the request
  path, and simulates resource creation, searches and commands for POSTs.
- `proxyrules`: evaluates an ordered YAML rules file. The first matching rule serves a
  `file:///` fixture (with the rule's optional `status` and `response_headers`),
  reverse-proxies to a real service, or redirects. In record mode
  (`proxyrules_record_mode`) a missing fixture is recorded from the next matching URL
  rule. Rules match on path, method and `headers`/`query`/`body`/`json` predicates, and
  every response is stamped with `X-Mockstack-Result` and `X-Mockstack-Rule`.

Both share `CreateMixin` for simulated creates. Settings come from pydantic-settings:
CLI flags, `MOCKSTACK__*` environment variables, or a `.env` file.

## Layout

- `mockstack/main.py`: app factory (`create_app`) and the `mockstack` CLI entry point
- `mockstack/cli.py`: the command line: rich-argparse help, `--version`, and
  configuration errors (`ValidationError`, `SettingsError`, `RulesFileError`) printed
  without a traceback, naming each setting by flag and environment variable, exit status 2
- `mockstack/config.py`: `Settings`, whose attribute docstrings are the `--help` text,
  and `SettingsDependencyError` for checks across settings;
  `mockstack/constants.py`: enums, header names
- `mockstack/strategies/`: `base.py`, `filefixtures.py`, `proxyrules.py`,
  `create_mixin.py`, `factory.py`
- `mockstack/rules.py`: the proxyrules `Rule`: predicates, load-time validation,
  template context
- `mockstack/recording.py`: record-mode building blocks: fixture encoding that renders
  back to the exact body, the recorded marker, root confinement and atomic writes
- `mockstack/templating.py`: Jinja environment and path-to-template-name resolution
- `mockstack/intent.py`, `mockstack/identifiers.py`: POST intent (search, command,
  create) and path-identifier heuristics
- `mockstack/routers/`: the catch-all route; every path, `/` included, reaches the strategy.
  FastAPI's `/docs`, `/redoc`, `/openapi.json` and `/docs/oauth2-redirect` routes are
  only registered, ahead of the catch-all, when `openapi_docs_enabled` is set
- `mockstack/tests/`: unit tests; `conftest.py` holds fixtures shared by unit and live
  tests (`make_settings`, `make_request`, `write_rules`, `write_template`, `span`, and
  `asgi_client`, an httpx client that calls the `app` fixture in-process), and
  `strategies/conftest.py` adds strategy helpers (`traced_request`,
  `proxyrules_strategy`, `apply_rule`, `upstream_send`, `span_attributes`). Build settings with
  `make_settings`: it ignores
  `MOCKSTACK__*` environment variables and `.env` files
- `mockstack/tests/live/`: live tests against real uvicorn servers on loopback sockets;
  `conftest.py` provides the session-scoped recording echo `upstream`, the module-scoped
  `mockstack_server`, `proxyrules_settings` and `render_rules`; `test_record_mode_live.py`
  records into temporary directories, never the repository
- `examples/`: runnable examples; `examples/proxyrules-cookbook/` holds the files
  embedded in the cookbook docs page
- `docs/`: the MkDocs Material site (`mkdocs.yml`); the home page is `README.md`

## Commands

```bash
uv sync                                         # install
uv run pytest -q --cov=mockstack                # unit tests; live tests are deselected
uv run pytest -m slow mockstack/tests/live -v   # live socket tests
uv run mypy mockstack
uvx ruff check && uvx ruff format --check
cp README.md docs/ && uvx --with mkdocs-material mkdocs build --strict
uvx pre-commit run --all-files                  # ruff, mypy, unit tests with coverage >= 90%
```

mockstack requires Python 3.13 or later; CI tests 3.13 and 3.14. Ruff (line length 120)
and mypy are configured in `pyproject.toml`: production code must be fully annotated,
and a `# noqa` names its rule code with the reason on the line above. CI and pre-commit
pin ruff (0.16.7); if a newer `uvx ruff` reports findings they do not, run
`uvx ruff@0.16.7`. Coverage measures production code only, and the pre-commit pytest
hook fails below 90%.

If `VIRTUAL_ENV` points at another checkout, `unset VIRTUAL_ENV` first so `uv` uses
this project's `.venv`.

The docs build copies `README.md` to `docs/README.md` as the site's home page. That
copy is a build artifact and is gitignored: never commit it. The build is strict and
`pymdownx.snippets` has `check_paths: true`, so a broken link or a missing embedded
file fails it. CI runs the unit tests, the live tests, mypy, ruff and the docs build.

## Conventions

- **TDD.** Write the failing test first. Unit-test logic; add a live test when the
  behaviour depends on real sockets, HTTP framing or a real upstream.
- **Live tests are marked `slow`** (`pytestmark = pytest.mark.slow`). `pyproject.toml`
  deselects them by default, so run them explicitly.
- **Docs examples must be backed by tests.** Cookbook recipes are real files under
  `examples/proxyrules-cookbook/`, embedded in `docs/guides/proxyrules-cookbook.md` with
  `--8<--`. `mockstack/tests/live/test_cookbook.py` runs every `curl` command on that
  page, and checks the page embeds every recipe file and that the README's
  proxyrules example matches recipe 1. Change a recipe's files, page section and test
  together. `mockstack/tests/test_docs_yaml.py` checks that every YAML block in the
  docs parses, and `test_docs_settings.py` that every `MOCKSTACK__*` variable in the
  docs, examples and `.env.example` files names a real setting.
- **Regexes in YAML** go in plain or single-quoted scalars: a double-quoted `"\1"`
  does not parse.
- **Fail at load, not per request.** Rules are validated and compiled when the
  strategy is constructed; a file that does not load raises `RulesFileError`, naming
  the file and the rule by position. Every `proxyrules` response, including errors, carries the
  result headers.
- **Keep names generic** in code, tests, docs and examples: projects service,
  analytics SQL gateway, `sales_facts`, orders, users. Never use company, product or
  internal service names.
- **Branches.** Pushes to `main` and to any `docs/**` branch deploy the docs site
  (`.github/workflows/publish-docs.yml`), so never push a `docs/...` branch casually.
  Use `feat/`, `fix/` and similar prefixes for working branches.
- **Commits.** Conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `ci:`). Stage files by explicit path. Commit trailers are added by the tool, so do
  not type them by hand.

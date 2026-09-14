# CLAUDE.md

Guidance for AI coding agents and contributors working in this repository.

## What mockstack is

mockstack is an API-mocking service built on FastAPI. A catch-all route hands every
request to one *strategy*, selected with the `strategy` setting:

- `filefixtures`: renders Jinja templates from `templates_dir`, chosen from the request
  path, and simulates resource creation, searches and commands for POSTs.
- `proxyrules`: evaluates an ordered YAML rules file. The first matching rule serves a
  `file:///` fixture, reverse-proxies to a real service, or redirects. Rules match on
  path, method and `headers`/`query`/`body`/`json` predicates, and every response is
  stamped with `X-Mockstack-Result` and `X-Mockstack-Rule`.

Both share `CreateMixin` for simulated creates. Settings come from pydantic-settings:
CLI flags, `MOCKSTACK__*` environment variables, or a `.env` file.

## Layout

- `mockstack/main.py`: app factory (`create_app`) and the `mockstack` CLI entry point
- `mockstack/config.py`: `Settings`; `mockstack/constants.py`: enums, header names
- `mockstack/strategies/`: `base.py`, `filefixtures.py`, `proxyrules.py`,
  `create_mixin.py`, `factory.py`
- `mockstack/rules.py`: the proxyrules `Rule`: predicates, load-time validation,
  template context
- `mockstack/templating.py`: Jinja environment and path-to-template-name resolution
- `mockstack/routers/`: catch-all and homepage routes
- `mockstack/tests/`: unit tests
- `mockstack/tests/live/`: live tests against real uvicorn servers on loopback sockets;
  `conftest.py` provides `upstream` (a recording echo server), `mockstack_server`,
  `write_rules` and `proxyrules_settings`
- `examples/`: runnable examples; `examples/proxyrules-cookbook/` holds the files
  embedded in the cookbook docs page
- `docs/`: the MkDocs Material site (`mkdocs.yml`); the home page is `README.md`

## Commands

```bash
uv sync                                         # install
uv run pytest -q --cov=mockstack                # unit tests; live tests are deselected
uv run pytest -m slow mockstack/tests/live -v   # live socket tests
uv run mypy mockstack
uvx ruff check && uvx ruff format
cp README.md docs/ && uvx --with mkdocs-material mkdocs build --strict
```

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
  docs parses.
- **Regexes in YAML** go in plain or single-quoted scalars: a double-quoted `"\1"`
  does not parse.
- **Fail at load, not per request.** Rules are validated and compiled when the
  strategy is constructed. Every `proxyrules` response, including errors, carries the
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

"""Live test harness: real uvicorn servers on loopback sockets.

These tests are marked ``slow`` and excluded by default. Run with ``uv run pytest -m slow``.

One recording echo ``upstream`` serves the whole session. Mockstack servers are started
per rules set and asked to stop when the module that started them ends. Every server
binds its socket before uvicorn starts, so there is no port to race for, and counts as
ready once uvicorn reports that startup finished, without polling it over HTTP. All
servers are joined when the session ends.
"""

import asyncio
import socket
import string
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from mockstack.config import Settings
from mockstack.constants import ProxyRulesRedirectVia
from mockstack.main import create_app

STARTUP_TIMEOUT = 10.0
SHUTDOWN_TIMEOUT = 10.0

# mockstack's default logging config replaces the root logger's handlers with a console
# handler, which prints server logs over pytest's output and detaches its log capture.
# Live servers leave the test process's logging as it is.
UNCHANGED_LOGGING: dict[str, Any] = {"version": 1, "disable_existing_loggers": False}


class _Server(uvicorn.Server):
    """A uvicorn server that signals when startup has finished, successfully or not."""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.startup_finished = threading.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            await super().startup(sockets=sockets)
        finally:
            self.startup_finished.set()

    def run(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            super().run(sockets=sockets)
        finally:
            # Also covers a failure before startup, such as loading the app.
            self.startup_finished.set()


@dataclass
class LiveServer:
    base_url: str
    server: _Server
    thread: threading.Thread
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request_stop(self) -> None:
        self.server.should_exit = True

    def stop(self) -> None:
        self.request_stop()
        self.thread.join(SHUTDOWN_TIMEOUT)
        if self.thread.is_alive():
            raise RuntimeError(
                f"server on {self.base_url} did not stop within {SHUTDOWN_TIMEOUT}s"
            )


def serve(app: FastAPI) -> LiveServer:
    """Serve ``app`` from a background thread; return once it accepts connections."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    server = _Server(uvicorn.Config(app, log_config=None, log_level="warning"))
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [sock]},
        name=f"live-server-{port}",
        daemon=True,
    )
    thread.start()
    live = LiveServer(base_url=f"http://{host}:{port}", server=server, thread=thread)

    finished = server.startup_finished.wait(STARTUP_TIMEOUT)
    if not (finished and server.started and thread.is_alive()):
        live.request_stop()
        sock.close()
        reason = (
            "failed to start" if finished else f"did not start in {STARTUP_TIMEOUT}s"
        )
        raise RuntimeError(f"server on {live.base_url} {reason}")
    return live


@pytest.fixture(scope="session")
def _live_servers() -> Iterator[list[LiveServer]]:
    """Every live server started in the session, joined when the session ends.

    Each server is asked to stop when the fixture that started it goes out of scope.
    Joining them all here lets their shutdowns (about 0.2s each in uvicorn) run at the
    same time instead of one module after another.
    """
    servers: list[LiveServer] = []
    yield servers
    for live in servers:
        live.request_stop()
    for live in servers:
        live.stop()


async def _client_disconnected(request: Request) -> None:
    """Return once the client that sent ``request`` has disconnected."""
    while (await request.receive())["type"] != "http.disconnect":
        pass


@pytest.fixture(scope="session")
def upstream(_live_servers) -> Iterator[LiveServer]:
    """Echo server, shared by the whole session, that records every request it echoes.

    ``calls`` is cleared before every live test (see ``_clear_upstream_calls``).
    """
    calls: list[dict[str, Any]] = []
    app = FastAPI()

    @app.get("/cookies")
    async def cookies():
        # Registered before the catch-all: a response with repeated Set-Cookie headers.
        response = JSONResponse({"source": "upstream"})
        response.set_cookie("first", "1")
        response.set_cookie("second", "2")
        return response

    @app.api_route("/sized", methods=["GET", "HEAD"])
    async def sized():
        # Registered before the catch-all: a fixed 1234-byte body for GET and HEAD.
        return Response(content=b"x" * 1234, media_type="application/octet-stream")

    @app.get("/slow")
    async def slow(request: Request):
        # Registered before the catch-all: answers after three seconds, for timeouts,
        # unless the client (a timed-out proxy request) disconnects first, so no
        # request outlives the test that sent it.
        try:
            await asyncio.wait_for(_client_disconnected(request), timeout=3)
        except TimeoutError:
            pass
        return {"source": "upstream", "path": "/slow"}

    @app.api_route(
        "/{p:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    async def echo(request: Request, p: str):
        body = await request.body()
        call = {
            "path": "/" + p,
            "method": request.method,
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "body": body.decode(),
        }
        calls.append(call)
        return {"source": "upstream", **call}

    live = serve(app)
    live.calls = calls
    _live_servers.append(live)
    yield live
    live.request_stop()


@pytest.fixture(autouse=True)
def _clear_upstream_calls(upstream: LiveServer) -> None:
    """Every live test starts with no recorded upstream calls."""
    upstream.calls.clear()


@pytest.fixture(scope="session")
def proxyrules_settings(make_settings) -> Callable[..., Settings]:
    """Factory: settings for a live proxyrules server on ``rules_file``.

    Every option the live tests rely on is passed explicitly, so ``MOCKSTACK__*``
    environment variables cannot change it, and ``make_settings`` skips any ``.env``
    file. ``overrides`` still take precedence.
    """

    def _settings(rules_file: Path, **overrides: Any) -> Settings:
        options: dict[str, Any] = {
            "strategy": "proxyrules",
            "proxyrules_rules_filename": rules_file,
            "proxyrules_redirect_via": ProxyRulesRedirectVia.REVERSE_PROXY,
            "proxyrules_simulate_create_on_missing": False,
            "logging": UNCHANGED_LOGGING,
            **overrides,
        }
        return make_settings(**options)

    return _settings


@pytest.fixture(scope="module")
def mockstack_server(
    _live_servers, proxyrules_settings, write_rules
) -> Iterator[Callable[..., LiveServer]]:
    """Factory: start mockstack for the rest of the module on a rules file or a list of
    rules; ``overrides`` go to ``proxyrules_settings``.

    The servers a module started are asked to stop when it ends (and joined when the
    session ends).
    """
    started: list[LiveServer] = []

    def _start(rules: Path | list[dict[str, Any]], **overrides: Any) -> LiveServer:
        rules_file = rules if isinstance(rules, Path) else write_rules(rules)
        live = serve(create_app(proxyrules_settings(rules_file, **overrides)))
        started.append(live)
        _live_servers.append(live)
        return live

    yield _start
    for live in started:
        live.request_stop()


@pytest.fixture(scope="session")
def render_rules(tmp_path_factory) -> Callable[..., Path]:
    """Factory: an example's rules file with its ``${VAR}`` placeholders substituted,
    written to a new temporary ``rules.local.yml``.

    Like the example READMEs' ``envsubst`` step, other ``$`` characters (regex anchors)
    are left alone; every ``${...}`` placeholder must be given a value.
    """

    def _render(rules_file: Path, **values: str) -> Path:
        rendered = string.Template(rules_file.read_text()).safe_substitute(values)
        assert "${" not in rendered, f"unsubstituted placeholder in {rules_file}"
        path = tmp_path_factory.mktemp("rules") / "rules.local.yml"
        path.write_text(rendered)
        return path

    return _render

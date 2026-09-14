"""Live test harness: real uvicorn servers on loopback sockets.

These tests are marked ``slow`` and excluded by default. Run with ``uv run pytest -m slow``.
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mockstack.config import OpenTelemetrySettings, Settings
from mockstack.main import create_app


@dataclass
class LiveServer:
    base_url: str
    calls: list[dict] = field(default_factory=list)
    _server: uvicorn.Server | None = None

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app: FastAPI) -> LiveServer:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{base_url}/__ready", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"server on {base_url} did not start")
    return LiveServer(base_url=base_url, _server=server)


@pytest.fixture
def upstream():
    """Echo server that records every request it receives."""
    live = LiveServer(base_url="")
    app = FastAPI()

    @app.get("/__ready")
    async def ready():
        # Registered before the catch-all so the readiness probe never hits
        # `echo()` below and never pollutes `live.calls`.
        return {"status": "ready"}

    @app.get("/cookies")
    async def cookies():
        # Registered before the catch-all: a response with repeated Set-Cookie headers.
        response = JSONResponse({"source": "upstream"})
        response.set_cookie("first", "1")
        response.set_cookie("second", "2")
        return response

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def echo(request: Request, p: str):
        body = await request.body()
        call = {
            "path": "/" + p,
            "method": request.method,
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "body": body.decode(),
        }
        live.calls.append(call)
        return {"source": "upstream", **call}

    served = _serve(app)
    live.base_url = served.base_url
    live._server = served._server
    yield live
    live.stop()


@pytest.fixture
def mockstack_server():
    """Factory: start mockstack with the given settings."""
    started: list[LiveServer] = []

    def _start(settings: Settings) -> LiveServer:
        live = _serve(create_app(settings))
        started.append(live)
        return live

    yield _start
    for live in started:
        live.stop()


def write_rules(tmp_path: Path, rules: list[dict]) -> Path:
    path = tmp_path / "rules.yml"
    path.write_text(yaml.safe_dump({"rules": rules}))
    return path


def proxyrules_settings(rules_file: Path, **overrides) -> Settings:
    return Settings(
        strategy="proxyrules",
        proxyrules_rules_filename=rules_file,
        opentelemetry=OpenTelemetrySettings(enabled=False),
        **overrides,
    )

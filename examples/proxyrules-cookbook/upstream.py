"""Echo "real service" for running the cookbook recipes by hand.

Answers every request with what it received. ``GET /slow`` waits three seconds
first, for the upstream-timeout example in recipe 6. The live tests use the
harness's own echo server (``mockstack/tests/live/conftest.py``) instead.

Usage: ``python upstream.py [port]`` (default port 8081).
"""

import asyncio
import sys

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/slow")
async def slow() -> dict:
    await asyncio.sleep(3)
    return {"source": "upstream", "path": "/slow"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def echo(request: Request, path: str) -> dict:
    body = await request.body()
    return {
        "source": "upstream",
        "path": "/" + path,
        "method": request.method,
        "query": dict(request.query_params),
        "body": body.decode(),
    }


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    uvicorn.run(app, host="127.0.0.1", port=port)

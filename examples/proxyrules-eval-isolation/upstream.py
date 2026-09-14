"""Minimal echo "real service" for manually running this example.

Not used by the live test (which uses the harness's own ``upstream`` fixture
instead) -- this is only so `README.md`'s "Run it" walkthrough has something for
the passthrough rules to reverse-proxy to.
"""

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def echo(request: Request, path: str) -> dict:
    body = await request.body()
    return {
        "source": "upstream",
        "path": "/" + path,
        "method": request.method,
        "body": body.decode(),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081)

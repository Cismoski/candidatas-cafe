"""Regressão: o middleware de rate limit não pode repetir http.response.start.

Bug da slowapi 0.1.10: em respostas de vários chunks (FileResponse > 64 KB)
o start era reenviado a cada chunk e o uvicorn derrubava a conexão.
"""

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware

from app.ratelimit import RateLimitMiddleware


def _app(middleware) -> FastAPI:
    app = FastAPI()
    app.state.limiter = Limiter(key_func=lambda *_: "ip", default_limits=["100/minute"])
    app.add_middleware(middleware)

    @app.get("/big")
    def big(request: Request):
        return StreamingResponse(iter([b"a" * 10, b"b" * 10, b"c" * 10]))

    return app


def _messages(app: FastAPI) -> list[dict]:
    sent: list[dict] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/big",
        "raw_path": b"/big",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "app": app,
    }

    first = True

    async def receive():
        # Como um servidor real: entrega o corpo uma vez e depois só retorna
        # quando o cliente desconecta (aqui, nunca; a resposta termina antes).
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(msg):
        sent.append(msg)

    asyncio.run(app(scope, receive, send))
    return sent


def test_single_response_start_with_chunked_body():
    msgs = _messages(_app(RateLimitMiddleware))
    types = [m["type"] for m in msgs]
    assert types.count("http.response.start") == 1
    assert types[0] == "http.response.start"
    body = b"".join(m.get("body", b"") for m in msgs if m["type"] == "http.response.body")
    assert body == b"a" * 10 + b"b" * 10 + b"c" * 10


@pytest.mark.parametrize("middleware", [SlowAPIASGIMiddleware])
def test_upstream_bug_still_present(middleware):
    """Documenta o bug original; se a slowapi corrigir, este teste avisa que
    o wrapper pode ser removido."""
    types = [m["type"] for m in _messages(_app(middleware))]
    assert types.count("http.response.start") > 1

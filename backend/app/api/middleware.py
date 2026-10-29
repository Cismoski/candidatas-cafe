"""Middlewares ASGI puros da API (ordem de montagem em main.create_app)."""

import logging

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("cafe")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=31536000"),
]


class SecurityHeadersMiddleware:
    """Acrescenta headers de segurança e Cache-Control: no-store por padrão."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                if b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class InternalErrorMiddleware:
    """Erro inesperado vira 500 JSON DENTRO da camada de CORS.

    O tratamento padrão do Starlette (ServerErrorMiddleware) fica fora de todos
    os middlewares: a resposta 500 sairia sem Access-Control-Allow-Origin, o
    navegador veria "erro de rede" e a interface diria que a API está dormindo.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            log.exception("erro inesperado em %s %s", scope["method"], scope["path"])
            if started:  # a resposta já começou: nada a fazer além de encerrar
                raise
            response = JSONResponse({"detail": "Erro inesperado na API. Tente de novo."}, 500)
            await response(scope, receive, send)

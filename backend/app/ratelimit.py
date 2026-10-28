"""Middleware de rate limit padrão (slowapi), corrigido para respostas em vários chunks.

O SlowAPIASGIMiddleware da slowapi 0.1.10 adia o http.response.start para
poder editar headers e o reenvia antes de CADA http.response.body. Com uma
resposta de um chunk só isso passa despercebido; com FileResponse acima de
64 KB (PNG das sobreposições, GeoJSON) o servidor recebe um segundo
"start", o uvicorn aborta a conexão e o navegador vê "Failed to fetch".

Aqui o start é enviado uma única vez, junto do primeiro chunk.
"""

from slowapi.middleware import SlowAPIASGIMiddleware, _ASGIMiddlewareResponder
from starlette.types import Message, Receive, Scope, Send


class _SingleStartResponder(_ASGIMiddlewareResponder):
    def __init__(self, app):
        super().__init__(app)
        self._started = False

    async def send_wrapper(self, message: Message) -> None:
        if message["type"] == "http.response.body" and self._started:
            await self.send(message)
            return
        if message["type"] == "http.response.body":
            self._started = True
        await super().send_wrapper(message)


class RateLimitMiddleware(SlowAPIASGIMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        await _SingleStartResponder(self.app)(scope, receive, send)

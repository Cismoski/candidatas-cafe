"""Rate limit: middleware da slowapi corrigido para respostas em vários chunks, e as chaves (IP, usuário).

O SlowAPIASGIMiddleware da slowapi 0.1.10 adia o http.response.start para
poder editar headers e o reenvia antes de CADA http.response.body. Com uma
resposta de um chunk só isso passa despercebido; com FileResponse acima de
64 KB (PNG das sobreposições, GeoJSON) o servidor recebe um segundo
"start", o uvicorn aborta a conexão e o navegador vê "Failed to fetch".

Aqui o start é enviado uma única vez, junto do primeiro chunk.
"""

from slowapi.middleware import SlowAPIASGIMiddleware, _ASGIMiddlewareResponder
from starlette.requests import Request
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


# --- chaves do rate limit -------------------------------------------------------------
def client_ip(request: Request) -> str:
    """IP real do cliente para o rate limit.

    Atrás do proxy do Render a conexão vem do proxy; o IP do cliente está no
    X-Forwarded-For. Só as últimas `trusted_proxy_hops` entradas foram
    acrescentadas por proxies confiáveis; as anteriores vêm do cliente e podem
    ser forjadas. Por isso usamos a N-ésima entrada a partir da DIREITA, e não
    a primeira (que é o que o --proxy-headers do uvicorn faz).
    """
    hops = request.app.state.services.settings.trusted_proxy_hops
    xff = request.headers.get("x-forwarded-for")
    if hops and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-min(hops, len(parts))]
    return request.client.host if request.client else "desconhecido"


def user_or_ip(request: Request) -> str:
    """Chave de rate limit: usuário autenticado (preenchido por current_user) ou IP."""
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{client_ip(request)}"

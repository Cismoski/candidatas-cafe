"""API FastAPI. Todos os endpoints exigem sessão, exceto /health e /auth/google."""

import asyncio
import contextlib
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import chat
from .auth import (
    BearerPrecheckMiddleware,
    CurrentUser,
    GoogleVerifier,
    InvalidGoogleToken,
    current_user,
    issue_token,
    verify_google_id_token,
)
from .breaker import CircuitBreaker
from .db import Database, DuplicateRequest, QuotaExceeded, now
from .jobs import JobRunner
from .llm import ChatModel, GeminiChat
from .processing.config import ClassificationConfig, load_config
from .ratelimit import RateLimitMiddleware
from .settings import Settings, get_settings
from .storage import DOWNLOADS, INPUT_NAMES, Storage
from .uploads import (
    BodySizeLimitMiddleware,
    RasterLimits,
    UploadRejected,
    save_upload,
    validate_multispectral,
    validate_scl,
)

log = logging.getLogger("globalwatch")

DEFAULT_MAX_BODY = 64 * 1024  # JSON de login, etc.

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


IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
UPLOAD_FIELDS = {"primary", "scl", "secondary"}


# --- IP do cliente atrás de proxy ---------------------------------------------------
def client_ip(request: Request) -> str:
    """IP real do cliente para o rate limit.

    Atrás do proxy do Render a conexão vem do proxy; o IP do cliente está no
    X-Forwarded-For. Só as últimas `trusted_proxy_hops` entradas foram
    acrescentadas por proxies confiáveis; as anteriores vêm do cliente e podem
    ser forjadas. Por isso usamos a N-ésima entrada a partir da DIREITA, e não
    a primeira (que é o que o --proxy-headers do uvicorn faz).
    """
    hops = request.app.state.settings.trusted_proxy_hops
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


# --- modelos -------------------------------------------------------------------
class GoogleLogin(BaseModel):
    credential: str = Field(min_length=10, max_length=4096)


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (tipo do token, não segredo)
    expires_in: int
    user: dict


class AnalysisItem(BaseModel):
    id: str
    status: Literal["pending", "processing", "done", "failed"]
    error: str | None
    title: str
    has_scl: bool
    has_secondary: bool
    created_at: str
    updated_at: str
    expires_at: str


class AnalysisOut(AnalysisItem):
    summary: dict | None = None


def _out(a: dict, retention_h: int, model: type[AnalysisItem] = AnalysisOut) -> AnalysisItem:
    expires = datetime.fromisoformat(a["created_at"]) + timedelta(hours=retention_h)
    return model(**a, expires_at=expires.isoformat(timespec="seconds"))


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=chat.MAX_MESSAGE_CHARS)


class ChatMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    source: Literal["gemini", "automatica"] | None
    notice: str | None
    created_at: str


class ChatOut(BaseModel):
    messages: list[ChatMessage]
    remaining_today: int | None = None


NOT_FOUND = HTTPException(404, "Análise não encontrada.")
_DEFAULT = object()


def default_chat_model(settings: Settings) -> ChatModel | None:
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    if not key.strip():
        return None
    return GeminiChat(key, settings.gemini_model, settings.gemini_timeout_seconds)


# --- retenção -------------------------------------------------------------------
def sweep(db: Database, storage: Storage, settings: Settings) -> int:
    expired = db.purge_expired(
        now() - timedelta(hours=settings.retention_hours),
        now() - timedelta(days=settings.user_retention_days),
    )
    for owner_id, analysis_id in expired:
        storage.remove_analysis(owner_id, analysis_id)
    storage.remove_orphans(db.analysis_ids())
    return len(expired)


async def _sweep_loop(app: FastAPI) -> None:
    s: Settings = app.state.settings
    while True:
        try:
            n = await run_in_threadpool(sweep, app.state.db, app.state.storage, s)
            if n:
                log.info("retenção: %d análises apagadas", n)
        except Exception:
            log.exception("falha na limpeza de retenção")
        await asyncio.sleep(s.retention_sweep_minutes * 60)


# --- fábrica da aplicação ----------------------------------------------------------
def create_app(
    settings: Settings | None = None,
    google_verifier: GoogleVerifier = verify_google_id_token,
    classification: ClassificationConfig | None = None,
    chat_model: ChatModel | None | object = _DEFAULT,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db.fail_interrupted()
        task = asyncio.create_task(_sweep_loop(app))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        app.state.jobs.shutdown()

    app = FastAPI(title="Global Watch — café", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    db = app.state.db = Database(settings.db_path)
    storage = app.state.storage = Storage(settings.data_dir)
    app.state.cfg = classification or load_config()
    app.state.jobs = JobRunner(
        db,
        storage,
        app.state.cfg,
        isolate=settings.job_isolation,
        timeout_s=settings.job_timeout_seconds,
    )
    app.state.chat_model = default_chat_model(settings) if chat_model is _DEFAULT else chat_model
    app.state.breaker = CircuitBreaker(
        settings.chat_breaker_failures, settings.chat_breaker_cooldown_seconds
    )
    # Um limiter por app, em memória do processo. O deploy roda 1 worker numa
    # única instância; com réplicas, o storage precisaria ser Redis.
    limiter = Limiter(key_func=client_ip, default_limits=["120/minute"])
    app.state.limiter = limiter
    limits = RasterLimits(max_dim=settings.max_raster_dim)

    # Ordem: o último adicionado é o mais externo.
    #   CORS -> limite de corpo -> headers -> pré-checagem do Bearer -> rate limit -> rotas
    # Todos são ASGI puros: BaseHTTPMiddleware embrulha o receive num task group
    # e transformaria o 413 do limite de corpo num ExceptionGroup (500).
    # CORS por fora para que até 401/413/429 levem os headers e o navegador
    # consiga mostrar a mensagem.
    app.add_middleware(RateLimitMiddleware)  # slowapi corrigido (ver ratelimit.py)
    app.add_middleware(BearerPrecheckMiddleware, routes={("POST", "/analyses")})
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        BodySizeLimitMiddleware,
        default_max=DEFAULT_MAX_BODY,
        overrides={("POST", "/analyses"): settings.max_upload_bytes},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # Bearer no header; nenhum cookie
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            {"detail": f"Muitas requisições ({exc.detail}). Aguarde e tente de novo."},
            status_code=429,
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        # Sem ecoar o valor enviado ("input"): no login ele seria o token do Google.
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    User = Annotated[CurrentUser, Depends(current_user)]

    # --- públicos --------------------------------------------------------------
    @app.get("/health")
    @limiter.exempt
    async def health():  # async: não depende do threadpool
        assistant = "automatico" if app.state.chat_model is None else app.state.breaker.state
        return {"status": "ok", "assistente": assistant}

    @app.post("/auth/google", response_model=Session)
    @limiter.limit("10/minute")
    def login_google(request: Request, body: GoogleLogin):
        try:
            identity = google_verifier(body.credential, settings.google_client_id)
        except InvalidGoogleToken:
            raise HTTPException(401, "Login com Google inválido.") from None
        user = db.upsert_user(identity.sub, identity.email, identity.name)
        token, ttl = issue_token(user["id"], settings)
        return Session(
            access_token=token,
            expires_in=ttl,
            user={"id": user["id"], "email": user["email"], "name": user["name"]},
        )

    # --- autenticados ------------------------------------------------------------
    @app.post("/auth/logout", status_code=204)
    def logout(user: User):
        db.revoke_token(user.jti, datetime.fromtimestamp(user.expires_at_ts, UTC))
        return Response(status_code=204)

    @app.get("/me")
    def me(user: User):
        u = db.get_user(user.id)
        return {"id": u["id"], "email": u["email"], "name": u["name"]}

    @app.get("/analyses", response_model=list[AnalysisItem])
    def list_analyses(user: User):
        return [_out(a, settings.retention_hours, AnalysisItem) for a in db.list_analyses(user.id)]

    @app.post(
        "/analyses",
        response_model=AnalysisOut,
        status_code=202,
        openapi_extra={
            "requestBody": {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["primary"],
                            "properties": {
                                "primary": {"type": "string", "format": "binary"},
                                "scl": {"type": "string", "format": "binary"},
                                "secondary": {"type": "string", "format": "binary"},
                                "title": {"type": "string", "maxLength": 80},
                            },
                        }
                    }
                },
                "required": True,
            }
        },
    )
    @limiter.limit("3/minute", key_func=user_or_ip)
    @limiter.limit("30/day", key_func=client_ip)
    async def create_analysis(request: Request, response: Response, user: User):
        idem = request.headers.get("idempotency-key")
        if idem is not None and not IDEMPOTENCY_KEY.fullmatch(idem):
            raise HTTPException(422, "Idempotency-Key inválida (8-64 caracteres [A-Za-z0-9_-]).")
        if idem:
            # Repetição de uma requisição já aceita (ex.: retry após timeout)
            existing = await run_in_threadpool(db.find_by_idempotency_key, user.id, idem)
            if existing:
                response.status_code = 200
                return _out(existing, settings.retention_hours)
        if await run_in_threadpool(db.count_active) >= settings.max_queued_jobs:
            raise HTTPException(503, "Fila de processamento cheia. Tente em alguns minutos.")

        try:
            form = await request.form(max_files=3, max_fields=1, max_part_size=1024)
        except MultiPartException as e:
            raise HTTPException(400, f"Formulário inválido: {e.message}") from None
        try:
            keys = [k for k, v in form.multi_items() if isinstance(v, UploadFile)]
            if set(keys) - UPLOAD_FIELDS or len(keys) != len(set(keys)):
                raise HTTPException(422, "Campos de arquivo aceitos: primary, scl, secondary.")
            files = {k: form[k] for k in keys}
            title = form.get("title", "")
            if "primary" not in files:
                raise HTTPException(422, "Envie a imagem principal no campo 'primary'.")
            if not isinstance(title, str) or len(title) > 80:
                raise HTTPException(422, "Título deve ter no máximo 80 caracteres.")
            return await run_in_threadpool(_accept_upload, user, files, title, idem, response)
        finally:
            await form.close()

    def _accept_upload(
        user: CurrentUser, files: dict, title: str, idem: str | None, response: Response
    ) -> AnalysisOut:
        """Parte bloqueante (disco, rasterio, SQLite), executada no threadpool."""
        try:
            db.consume_quota(user.id, "upload", settings.uploads_per_day, timedelta(days=1))
        except QuotaExceeded:
            raise HTTPException(
                429, f"Limite de {settings.uploads_per_day} análises por dia atingido."
            ) from None

        analysis_id = str(uuid.uuid4())
        inputs = storage.inputs_dir(user.id, analysis_id)
        try:
            for key in ("primary", "scl", "secondary"):
                if key not in files:
                    continue
                dest = inputs / INPUT_NAMES[key]
                save_upload(files[key], dest, settings.max_upload_bytes)
                if key == "scl":
                    validate_scl(dest, limits)
                else:
                    label = "Imagem principal" if key == "primary" else "Segunda data"
                    validate_multispectral(dest, limits, label)
        except UploadRejected as e:
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            # Rejeições não gastam a cota de análises, mas têm cota própria:
            # cada validação custa I/O e CPU.
            try:
                db.consume_quota(
                    user.id, "upload_rejected", 3 * settings.uploads_per_day, timedelta(days=1)
                )
            except QuotaExceeded:
                raise HTTPException(429, "Muitos arquivos inválidos hoje.") from None
            raise HTTPException(422, str(e)) from None
        except BaseException:
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            raise

        clean_title = " ".join(title.split()) or (files["primary"].filename or "Análise")[:80]
        try:
            db.create_analysis(
                analysis_id, user.id, clean_title, "scl" in files, "secondary" in files, idem
            )
        except DuplicateRequest:
            # Corrida entre duas requisições com a mesma chave: a outra venceu
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            response.status_code = 200
            return _out(db.find_by_idempotency_key(user.id, idem), settings.retention_hours)
        app.state.jobs.submit(user.id, analysis_id)
        return _out(db.get_analysis(analysis_id, user.id), settings.retention_hours)

    def _owned(analysis_id: str, user: CurrentUser) -> dict:
        try:
            uuid.UUID(analysis_id)
        except ValueError:
            raise NOT_FOUND from None
        a = db.get_analysis(analysis_id, user.id)
        if a is None:
            raise NOT_FOUND  # 404 também para análise de outro usuário: não revela existência
        return a

    def _done(analysis_id: str, user: CurrentUser) -> dict:
        a = _owned(analysis_id, user)
        if a["status"] != "done" or not a["summary"]:
            raise HTTPException(409, "O assistente fica disponível quando a análise terminar.")
        return a

    def _intro(a: dict) -> dict:
        # Abertura por template (não gravada): números exatos e sem gastar cota
        return {
            "id": 0,
            "role": "assistant",
            "content": chat.introduction(a["summary"], a["title"]),
            "source": "automatica",
            "notice": None,
            "created_at": a["updated_at"],
        }

    @app.get("/analyses/{analysis_id}/chat", response_model=ChatOut)
    def get_chat(analysis_id: str, user: User):
        a = _done(analysis_id, user)
        return ChatOut(messages=[_intro(a), *db.list_chat(analysis_id, user.id)])

    @app.post("/analyses/{analysis_id}/chat", response_model=ChatOut)
    @limiter.limit("10/minute", key_func=user_or_ip)
    def post_chat(request: Request, analysis_id: str, body: ChatIn, user: User):
        question = " ".join(body.message.split())
        if not question:
            raise HTTPException(422, "Escreva uma pergunta.")
        a = _done(analysis_id, user)
        try:
            remaining = db.consume_quota(
                user.id, "chat", settings.chat_messages_per_day, timedelta(days=1)
            )
        except QuotaExceeded:
            raise HTTPException(
                429,
                f"Limite de {settings.chat_messages_per_day} perguntas por dia atingido. "
                "As respostas já dadas continuam aqui.",
            ) from None
        history = db.list_chat(analysis_id, user.id, limit=2 * chat.HISTORY_TURNS)
        answer = chat.respond(
            question, a["summary"], history, app.state.chat_model, app.state.breaker
        )
        rows = db.add_chat_exchange(analysis_id, user.id, question, answer)
        if rows is None:  # apagada enquanto o modelo respondia
            raise NOT_FOUND
        return ChatOut(messages=rows, remaining_today=remaining)

    @app.get("/analyses/{analysis_id}", response_model=AnalysisOut)
    def get_analysis(analysis_id: str, user: User):
        return _out(_owned(analysis_id, user), settings.retention_hours)

    @app.get("/analyses/{analysis_id}/files/{name}")
    def download(analysis_id: str, name: str, user: User):
        a = _owned(analysis_id, user)
        if name not in DOWNLOADS:
            raise HTTPException(404, "Arquivo não encontrado.")
        if a["status"] != "done":
            raise HTTPException(409, "A análise ainda não terminou.")
        filename, media, attachment = DOWNLOADS[name]
        path = storage.outputs_dir(user.id, analysis_id) / filename
        if not path.is_file():
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(
            path,
            media_type=media,
            filename=f"cafe-{analysis_id[:8]}-{filename}" if attachment else None,
            content_disposition_type="attachment" if attachment else "inline",
            # no-store: depois de apagar/sair, nada fica no cache do navegador
            headers={"Cache-Control": "private, no-store"},
        )

    @app.delete("/analyses/{analysis_id}", status_code=204)
    def delete_analysis(analysis_id: str, user: User):
        _owned(analysis_id, user)
        # Banco primeiro: se o processo cair antes do rmtree, a varredura de
        # órfãos remove os arquivos. Um job em andamento é terminado.
        if db.delete_analysis(analysis_id, user.id):
            app.state.jobs.cancel(analysis_id)
            storage.remove_analysis(user.id, analysis_id)
        return Response(status_code=204)

    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()

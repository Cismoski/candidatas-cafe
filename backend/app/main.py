"""Raiz de composição: liga os ports aos adaptadores e monta a API.

Todos os endpoints exigem sessão, exceto /health e /auth/google. As rotas
ficam em app/api; aqui só se decide QUEM implementa cada port (SQLite, disco,
subprocesso, Google, Gemini) e em que ordem os middlewares envolvem a app.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool

from .api import routes_analyses, routes_auth, routes_chat
from .api.middleware import InternalErrorMiddleware, SecurityHeadersMiddleware
from .auth import BearerPrecheckMiddleware, verify_google_id_token
from .breaker import CircuitBreaker
from .db import Database, now
from .jobs import JobRunner
from .llm import GeminiChat
from .ports import ChatModel, FileStore, IdentityVerifier, Repository
from .processing.config import ClassificationConfig, load_config
from .ratelimit import RateLimitMiddleware, client_ip
from .services import Services
from .settings import Settings, get_settings
from .storage import Storage
from .uploads import BodySizeLimitMiddleware, RasterLimits

log = logging.getLogger("cafe")

DEFAULT_MAX_BODY = 64 * 1024  # JSON de login, etc.
_DEFAULT = object()


def default_chat_model(settings: Settings) -> ChatModel | None:
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    if not key.strip():
        return None
    return GeminiChat(
        key, settings.gemini_model, settings.gemini_timeout_seconds, settings.chat_max_concurrent
    )


# --- retenção -------------------------------------------------------------------
def sweep(db: Repository, storage: FileStore, settings: Settings) -> int:
    expired = db.purge_expired(
        now() - timedelta(hours=settings.retention_hours),
        now() - timedelta(days=settings.user_retention_days),
    )
    for owner_id, analysis_id in expired:
        storage.remove_analysis(owner_id, analysis_id)
    storage.remove_orphans(db.analysis_ids())
    return len(expired)


async def _sweep_loop(services: Services) -> None:
    while True:
        try:
            n = await run_in_threadpool(sweep, services.db, services.storage, services.settings)
            if n:
                log.info("retenção: %d análises apagadas", n)
        except Exception:
            log.exception("falha na limpeza de retenção")
        await asyncio.sleep(services.settings.retention_sweep_minutes * 60)


# --- fábrica da aplicação ----------------------------------------------------------
def create_app(
    settings: Settings | None = None,
    google_verifier: IdentityVerifier = verify_google_id_token,
    classification: ClassificationConfig | None = None,
    chat_model: ChatModel | None | object = _DEFAULT,
) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.db_path)
    storage = Storage(settings.data_dir)
    cfg = classification or load_config()
    services = Services(
        settings=settings,
        db=db,
        storage=storage,
        jobs=JobRunner(
            db,
            storage,
            cfg,
            isolate=settings.job_isolation,
            timeout_s=settings.job_timeout_seconds,
            reference_url=settings.mapbiomas_url,
        ),
        verify_identity=google_verifier,
        chat_model=default_chat_model(settings) if chat_model is _DEFAULT else chat_model,
        breaker=CircuitBreaker(
            settings.chat_breaker_failures, settings.chat_breaker_cooldown_seconds
        ),
        cfg=cfg,
        raster_limits=RasterLimits(max_dim=settings.max_raster_dim),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services.db.fail_interrupted()
        task = asyncio.create_task(_sweep_loop(services))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        services.jobs.shutdown()

    app = FastAPI(title="Candidatas a café", version="1.0.0", lifespan=lifespan)
    app.state.services = services
    # Um limiter por app, em memória do processo. O deploy roda 1 worker numa
    # única instância; com réplicas, o storage precisaria ser Redis.
    limiter = Limiter(key_func=client_ip, default_limits=["120/minute"])
    app.state.limiter = limiter

    # Ordem: o último adicionado é o mais externo.
    #   CORS -> limite de corpo -> headers -> erro 500 -> pré-checagem do Bearer
    #   -> rate limit -> rotas
    # Todos são ASGI puros: BaseHTTPMiddleware embrulha o receive num task group
    # e transformaria o 413 do limite de corpo num ExceptionGroup (500).
    # CORS por fora para que até 401/413/429 levem os headers e o navegador
    # consiga mostrar a mensagem.
    app.add_middleware(RateLimitMiddleware)  # slowapi corrigido (ver ratelimit.py)
    app.add_middleware(BearerPrecheckMiddleware, routes={("POST", "/analyses")})
    app.add_middleware(InternalErrorMiddleware)  # dentro de CORS e headers
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

    # Cada módulo registra as rotas direto na app, sem APIRouter: com include_router,
    # esta versão do FastAPI não expõe as rotas em app.routes, a slowapi deixa de
    # achar o endpoint e o limite padrão de 120/min some (teste em test_rate_limit).
    for module in (routes_auth, routes_chat, routes_analyses):
        module.register(app, services, limiter)
    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()

"""API FastAPI. Todos os endpoints exigem sessão, exceto /health e /auth/google."""

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool

from . import jobs
from .auth import (
    CurrentUser,
    GoogleVerifier,
    InvalidGoogleToken,
    current_user,
    issue_token,
    verify_google_id_token,
)
from .db import Database, QuotaExceeded, now
from .processing.config import ClassificationConfig, load_config
from .settings import Settings, get_settings
from .storage import DOWNLOADS, INPUT_NAMES, Storage
from .uploads import (
    LimitUploadSizeMiddleware,
    RasterLimits,
    UploadRejected,
    save_upload,
    validate_multispectral,
    validate_scl,
)

log = logging.getLogger("globalwatch")


def user_or_ip(request: Request) -> str:
    """Chave de rate limit: usuário autenticado (preenchido por current_user) ou IP."""
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{get_remote_address(request)}"


# --- modelos de resposta ---------------------------------------------------------
class GoogleLogin(BaseModel):
    credential: str = Field(min_length=10, max_length=4096)


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (tipo do token, não segredo)
    expires_in: int
    user: dict


class AnalysisItem(BaseModel):
    id: str
    status: str
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


NOT_FOUND = HTTPException(404, "Análise não encontrada.")


# --- retenção -------------------------------------------------------------------
def sweep(db: Database, storage: Storage, retention_hours: int) -> int:
    expired = db.purge_expired(now() - timedelta(hours=retention_hours))
    for owner_id, analysis_id in expired:
        storage.remove_analysis(owner_id, analysis_id)
    storage.remove_orphans(db.analysis_ids())
    return len(expired)


async def _sweep_loop(app: FastAPI) -> None:
    s: Settings = app.state.settings
    while True:
        try:
            n = await run_in_threadpool(sweep, app.state.db, app.state.storage, s.retention_hours)
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

    app = FastAPI(title="Global Watch — café", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.db_path)
    app.state.storage = Storage(settings.data_dir)
    app.state.cfg = classification or load_config()
    # Um limiter por app (memória do processo): sem estado global entre instâncias.
    # Instância única no plano gratuito; com várias réplicas, trocar por Redis.
    limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
    app.state.limiter = limiter

    limits = RasterLimits(max_dim=settings.max_raster_dim)

    # Ordem: o último adicionado é o mais externo. CORS por fora para que até
    # respostas 413/429 levem os headers e o navegador mostre a mensagem.
    app.add_middleware(
        LimitUploadSizeMiddleware, max_bytes=settings.max_upload_bytes, paths=("/analyses",)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # Bearer no header; nenhum cookie
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            {"detail": f"Muitas requisições ({exc.detail}). Aguarde e tente de novo."},
            status_code=429,
        )

    User = Annotated[CurrentUser, Depends(current_user)]

    # --- públicos --------------------------------------------------------------
    @app.get("/health")
    @limiter.exempt
    def health():
        return {"status": "ok"}

    @app.post("/auth/google", response_model=Session)
    @limiter.limit("10/minute")
    def login_google(request: Request, body: GoogleLogin):
        try:
            identity = google_verifier(body.credential, settings.google_client_id)
        except InvalidGoogleToken:
            raise HTTPException(401, "Login com Google inválido.") from None
        user = app.state.db.upsert_user(identity.sub, identity.email, identity.name)
        token, ttl = issue_token(user["id"], settings)
        return Session(
            access_token=token,
            expires_in=ttl,
            user={"id": user["id"], "email": user["email"], "name": user["name"]},
        )

    # --- autenticados ------------------------------------------------------------
    @app.post("/auth/logout", status_code=204)
    def logout(user: User):
        app.state.db.revoke_token(user.jti, datetime.fromtimestamp(user.expires_at_ts, UTC))
        return Response(status_code=204)

    @app.get("/me")
    def me(user: User):
        u = app.state.db.get_user(user.id)
        return {"id": u["id"], "email": u["email"], "name": u["name"]}

    @app.get("/analyses", response_model=list[AnalysisItem])
    def list_analyses(user: User):
        rows = app.state.db.list_analyses(user.id)
        return [_out(a, settings.retention_hours, AnalysisItem) for a in rows]

    @app.post("/analyses", response_model=AnalysisOut, status_code=202)
    @limiter.limit("3/minute", key_func=user_or_ip)
    @limiter.limit("30/day", key_func=get_remote_address)
    async def create_analysis(
        request: Request,
        background: BackgroundTasks,
        user: User,
        primary: Annotated[
            UploadFile, File(description="GeoTIFF 4 bandas uint16 (B02,B03,B04,B08)")
        ],
        scl: Annotated[UploadFile | None, File(description="SCL do Sentinel-2 (opcional)")] = None,
        secondary: Annotated[
            UploadFile | None, File(description="Mesma área em outra data (opcional)")
        ] = None,
        title: Annotated[str, Form(max_length=80)] = "",
    ):
        db: Database = app.state.db
        storage: Storage = app.state.storage
        try:
            db.consume_quota(user.id, "upload", settings.uploads_per_day, timedelta(days=1))
        except QuotaExceeded:
            raise HTTPException(
                429, f"Limite de {settings.uploads_per_day} análises por dia atingido."
            ) from None

        analysis_id = str(uuid.uuid4())
        inputs = storage.inputs_dir(user.id, analysis_id)
        files = {"primary": primary, "scl": scl, "secondary": secondary}

        def receive() -> None:
            for key, upload in files.items():
                if upload is None:
                    continue
                dest = inputs / INPUT_NAMES[key]
                save_upload(upload, dest, settings.max_upload_bytes)
                if key == "scl":
                    validate_scl(dest, limits)
                else:
                    label = "Imagem principal" if key == "primary" else "Segunda data"
                    validate_multispectral(dest, limits, label)

        try:
            await run_in_threadpool(receive)
        except UploadRejected as e:
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            raise HTTPException(422, str(e)) from None
        except BaseException:
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            raise

        clean_title = " ".join(title.split()) or (primary.filename or "Análise")[:80]
        db.create_analysis(
            analysis_id, user.id, clean_title, scl is not None, secondary is not None
        )
        background.add_task(
            jobs.process_analysis,
            db,
            storage,
            app.state.cfg,
            user.id,
            analysis_id,
            isolate=settings.job_isolation,
            timeout_s=settings.job_timeout_seconds,
        )
        return _out(db.get_analysis(analysis_id, user.id), settings.retention_hours)

    def _owned(analysis_id: str, user: CurrentUser) -> dict:
        try:
            uuid.UUID(analysis_id)
        except ValueError:
            raise NOT_FOUND from None
        a = app.state.db.get_analysis(analysis_id, user.id)
        if a is None:
            raise NOT_FOUND  # 404 também para análise de outro usuário: não revela existência
        return a

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
        path = app.state.storage.outputs_dir(user.id, analysis_id) / filename
        if not path.is_file():
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(
            path,
            media_type=media,
            filename=f"cafe-{analysis_id[:8]}-{filename}" if attachment else None,
            content_disposition_type="attachment" if attachment else "inline",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.delete("/analyses/{analysis_id}", status_code=204)
    def delete_analysis(analysis_id: str, user: User):
        _owned(analysis_id, user)
        # Banco primeiro: se o processo cair antes do rmtree, a varredura de
        # órfãos remove os arquivos. O job em andamento descarta o próprio resultado.
        if app.state.db.delete_analysis(analysis_id, user.id):
            app.state.storage.remove_analysis(user.id, analysis_id)
        return Response(status_code=204)

    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()

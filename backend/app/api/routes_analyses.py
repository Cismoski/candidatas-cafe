"""Análises: upload, listagem, consulta, downloads e exclusão."""

from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from slowapi import Limiter
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from ..auth import CurrentUser
from ..ports import DuplicateRequest, QuotaExceeded
from ..ratelimit import client_ip, user_or_ip
from ..services import Services
from ..storage import DOWNLOADS, INPUT_NAMES
from ..uploads import UploadRejected, save_upload, validate_multispectral, validate_scl
from ..values import AnalysisId, AnalysisTitle, IdempotencyKey
from .deps import User, owned
from .schemas import AnalysisItem, AnalysisOut, analysis_out

UPLOAD_FIELDS = {"primary", "scl", "secondary"}

UPLOAD_OPENAPI = {
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
}


def register(app: FastAPI, services: Services, limiter: Limiter) -> None:
    db, storage, settings = services.db, services.storage, services.settings
    retention_h = settings.retention_hours

    @app.get("/analyses", response_model=list[AnalysisItem])
    def list_analyses(user: User):
        return [analysis_out(a, retention_h, AnalysisItem) for a in db.list_analyses(user.id)]

    @app.post(
        "/analyses", response_model=AnalysisOut, status_code=202, openapi_extra=UPLOAD_OPENAPI
    )
    @limiter.limit("3/minute", key_func=user_or_ip)
    @limiter.limit("30/day", key_func=client_ip)
    async def create_analysis(request: Request, response: Response, user: User):
        raw_key = request.headers.get("idempotency-key")
        try:
            idem = None if raw_key is None else IdempotencyKey(raw_key)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if idem:
            # Repetição de uma requisição já aceita (ex.: retry após timeout)
            existing = await run_in_threadpool(db.find_by_idempotency_key, user.id, idem)
            if existing:
                response.status_code = 200
                return analysis_out(existing, retention_h)
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
            if "primary" not in files:
                raise HTTPException(422, "Envie a imagem principal no campo 'primary'.")
            try:
                title = AnalysisTitle.from_form(form.get("title", ""), files["primary"].filename)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
            return await run_in_threadpool(_accept_upload, user, files, title, idem, response)
        finally:
            await form.close()

    def _accept_upload(
        user: CurrentUser,
        files: dict,
        title: AnalysisTitle,
        idem: IdempotencyKey | None,
        response: Response,
    ) -> AnalysisOut:
        """Parte bloqueante (disco, rasterio, SQLite), executada no threadpool."""
        try:
            db.consume_quota(user.id, "upload", settings.uploads_per_day, timedelta(days=1))
        except QuotaExceeded:
            raise HTTPException(
                429, f"Limite de {settings.uploads_per_day} análises por dia atingido."
            ) from None

        analysis_id = AnalysisId.new()
        inputs = storage.inputs_dir(user.id, analysis_id)
        try:
            for key in ("primary", "scl", "secondary"):
                if key not in files:
                    continue
                dest = inputs / INPUT_NAMES[key]
                save_upload(files[key], dest, settings.max_upload_bytes)
                if key == "scl":
                    validate_scl(dest, services.raster_limits)
                else:
                    label = "Imagem principal" if key == "primary" else "Segunda data"
                    validate_multispectral(dest, services.raster_limits, label)
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

        try:
            db.create_analysis(
                analysis_id, user.id, title.value, "scl" in files, "secondary" in files, idem
            )
        except DuplicateRequest:
            # Corrida entre duas requisições com a mesma chave: a outra venceu
            storage.remove_analysis(user.id, analysis_id)
            db.release_quota(user.id, "upload")
            response.status_code = 200
            return analysis_out(db.find_by_idempotency_key(user.id, idem), retention_h)
        services.jobs.submit(user.id, analysis_id)
        return analysis_out(db.get_analysis(analysis_id, user.id), retention_h)

    @app.get("/analyses/{analysis_id}", response_model=AnalysisOut)
    def get_analysis(analysis_id: str, user: User):
        return analysis_out(owned(db, analysis_id, user)[1], retention_h)

    @app.get("/analyses/{analysis_id}/files/{name}")
    def download(analysis_id: str, name: str, user: User):
        aid, a = owned(db, analysis_id, user)
        if name not in DOWNLOADS:
            raise HTTPException(404, "Arquivo não encontrado.")
        if a["status"] != "done":
            raise HTTPException(409, "A análise ainda não terminou.")
        filename, media, attachment = DOWNLOADS[name]
        path = storage.outputs_dir(user.id, aid) / filename
        if not path.is_file():
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(
            path,
            media_type=media,
            filename=f"cafe-{aid[:8]}-{filename}" if attachment else None,
            content_disposition_type="attachment" if attachment else "inline",
            # no-store: depois de apagar/sair, nada fica no cache do navegador
            headers={"Cache-Control": "private, no-store"},
        )

    @app.delete("/analyses/{analysis_id}", status_code=204)
    def delete_analysis(analysis_id: str, user: User):
        aid, _ = owned(db, analysis_id, user)
        # Banco primeiro: se o processo cair antes do rmtree, a varredura de
        # órfãos remove os arquivos. Um job em andamento é terminado.
        if db.delete_analysis(aid, user.id):
            services.jobs.cancel(aid)
            storage.remove_analysis(user.id, aid)
        return Response(status_code=204)

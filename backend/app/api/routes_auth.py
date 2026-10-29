"""Saúde e sessão: /health, login com Google, logout e /me."""

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from slowapi import Limiter

from ..auth import issue_token
from ..ports import InvalidIdentity
from ..services import Services
from .deps import User
from .schemas import GoogleLogin, Session


def register(app: FastAPI, services: Services, limiter: Limiter) -> None:
    db, settings = services.db, services.settings

    @app.get("/health")
    @limiter.exempt
    async def health():  # async: não depende do threadpool
        assistant = "automatico" if services.chat_model is None else services.breaker.state
        return {"status": "ok", "assistente": assistant}

    @app.post("/auth/google", response_model=Session)
    @limiter.limit("10/minute")
    def login_google(request: Request, body: GoogleLogin):
        try:
            identity = services.verify_identity(body.credential, settings.google_client_id)
        except InvalidIdentity:
            raise HTTPException(401, "Login com Google inválido.") from None
        user = db.upsert_user(identity.sub, identity.email, identity.name)
        token, ttl = issue_token(user["id"], settings)
        return Session(
            access_token=token,
            expires_in=ttl,
            user={"id": user["id"], "email": user["email"], "name": user["name"]},
        )

    @app.post("/auth/logout", status_code=204)
    def logout(user: User):
        db.revoke_token(user.jti, datetime.fromtimestamp(user.expires_at_ts, UTC))
        return Response(status_code=204)

    @app.get("/me")
    def me(user: User):
        u = db.get_user(user.id)
        return {"id": u["id"], "email": u["email"], "name": u["name"]}

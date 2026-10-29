"""Assistente de cada análise: histórico e perguntas."""

from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request
from slowapi import Limiter

from .. import chat
from ..ports import QuotaExceeded
from ..ratelimit import user_or_ip
from ..services import Services
from .deps import NOT_FOUND, User, done
from .schemas import ChatIn, ChatOut


def _intro(a: dict) -> dict:
    # Abertura por template (não gravada): números exatos e sem gastar cota
    return {
        "id": 0,
        "role": "assistant",
        "content": chat.introduction(a["summary"]),
        "source": "automatica",
        "notice": None,
        "created_at": a["updated_at"],
    }


def register(app: FastAPI, services: Services, limiter: Limiter) -> None:
    db, settings = services.db, services.settings
    per_day = settings.chat_messages_per_day

    @app.get("/analyses/{analysis_id}/chat", response_model=ChatOut)
    def get_chat(analysis_id: str, user: User):
        aid, a = done(db, analysis_id, user)
        used = db.quota_used(user.id, "chat", timedelta(days=1))
        return ChatOut(
            messages=[_intro(a), *db.list_chat(aid, user.id)],
            remaining_today=max(0, per_day - used),
        )

    @app.post("/analyses/{analysis_id}/chat", response_model=ChatOut)
    @limiter.limit("10/minute", key_func=user_or_ip)
    def post_chat(request: Request, analysis_id: str, body: ChatIn, user: User):
        question = " ".join(body.message.split())
        if not question:
            raise HTTPException(422, "Escreva uma pergunta.")
        aid, a = done(db, analysis_id, user)
        try:
            remaining = db.consume_quota(user.id, "chat", per_day, timedelta(days=1))
        except QuotaExceeded:
            raise HTTPException(
                429,
                f"Limite de {per_day} perguntas por dia atingido. "
                "As respostas já dadas continuam aqui.",
            ) from None
        try:
            history = db.list_chat(aid, user.id, limit=chat.HISTORY_MESSAGES)
            answer = chat.respond(
                question, a["summary"], history, services.chat_model, services.breaker
            )
            rows = db.add_chat_exchange(aid, user.id, question, answer)
        except Exception:
            db.release_quota(user.id, "chat")  # a pergunta não foi respondida
            raise
        if rows is None:  # apagada enquanto o modelo respondia
            db.release_quota(user.id, "chat")
            raise NOT_FOUND
        return ChatOut(messages=rows, remaining_today=remaining)

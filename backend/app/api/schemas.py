"""Formatos de entrada e saída da API (pydantic)."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from .. import chat


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


def analysis_out(
    a: dict, retention_h: int, model: type[AnalysisItem] = AnalysisOut
) -> AnalysisItem:
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

"""Ports: o que as rotas e o assistente precisam do mundo de fora.

Cada port é um `Protocol` (tipagem estrutural): o adaptador não herda nada,
só precisa ter os mesmos métodos. A ligação entre port e adaptador acontece em
um lugar só, `create_app` (raiz de composição), e os testes trocam um
adaptador por um falso passando outro objeto para ela.

| Port               | Adaptador de produção          | Falso nos testes            |
|--------------------|--------------------------------|-----------------------------|
| IdentityVerifier   | auth.verify_google_id_token    | tests/api/conftest.py       |
| ChatModel          | llm.GeminiChat                 | FakeModel (test_chat_api)   |
| Repository         | db.Database (SQLite)           | Database em diretório tmp   |
| FileStore          | storage.Storage (disco)        | Storage em diretório tmp    |
| JobQueue           | jobs.JobRunner (subprocesso)   | JobRunner sem isolamento    |

O processamento (`app/processing`) não tem port: são funções puras sobre
arrays, chamadas pelo JobRunner. A referência MapBiomas é lida dentro do
subprocesso pela URL configurada.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable


# --- identidade ----------------------------------------------------------------------
@dataclass(frozen=True)
class Identity:
    """Usuário confirmado pelo provedor de login."""

    sub: str  # id estável no provedor
    email: str
    name: str | None


class InvalidIdentity(Exception):
    """Credencial recusada pelo provedor (assinatura, audiência, validade, e-mail)."""


@runtime_checkable
class IdentityVerifier(Protocol):
    def __call__(self, token: str, client_id: str) -> Identity: ...


# --- modelo de linguagem ---------------------------------------------------------------
@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str


class LLMError(Exception):
    """Falha do serviço (rede, timeout, 429, 5xx, chave inválida): conta no circuit breaker."""


class LLMSkipped(LLMError):
    """Sem veredito sobre a saúde do serviço: todas as vagas ocupadas, ou resposta
    vazia/bloqueada/cortada. NÃO conta no breaker: senão três perguntas que
    disparam o filtro de segurança desligariam o Gemini para todos."""


@runtime_checkable
class ChatModel(Protocol):
    def generate(self, system: str, history: list[Turn], message: str) -> str: ...


# --- persistência ------------------------------------------------------------------------
class QuotaExceeded(Exception):
    """consume_quota: limite da janela atingido (vira 429 na rota)."""


class DuplicateRequest(Exception):
    """create_analysis: Idempotency-Key já usada por este usuário (a outra requisição venceu)."""


@runtime_checkable
class Repository(Protocol):
    """Usuários, análises, cotas, chat e tokens revogados. Toda leitura de
    análise recebe o dono: não existe consulta "só pelo id"."""

    def upsert_user(self, google_sub: str, email: str, name: str | None) -> dict: ...
    def get_user(self, user_id: str) -> dict | None: ...
    def revoke_token(self, jti: str, expires_at: datetime) -> None: ...
    def is_revoked(self, jti: str) -> bool: ...

    def consume_quota(self, user_id: str, kind: str, limit: int, window: timedelta) -> int: ...
    def release_quota(self, user_id: str, kind: str) -> None: ...
    def quota_used(self, user_id: str, kind: str, window: timedelta) -> int: ...

    def create_analysis(
        self,
        analysis_id: str,
        owner_id: str,
        title: str,
        has_scl: bool,
        has_secondary: bool,
        idempotency_key: str | None = None,
    ) -> None: ...
    def get_analysis(self, analysis_id: str, owner_id: str) -> dict | None: ...
    def find_by_idempotency_key(self, owner_id: str, key: str) -> dict | None: ...
    def list_analyses(self, owner_id: str, limit: int = 50) -> list[dict]: ...
    def count_active(self) -> int: ...
    def set_status(
        self,
        analysis_id: str,
        status: str,
        *,
        error: str | None = None,
        summary: dict | None = None,
    ) -> bool: ...
    def delete_analysis(self, analysis_id: str, owner_id: str) -> bool: ...
    def fail_interrupted(self) -> int: ...
    def purge_expired(
        self, older_than: datetime, inactive_users_before: datetime
    ) -> list[tuple[str, str]]: ...
    def analysis_ids(self) -> set[str]: ...

    def list_chat(self, analysis_id: str, owner_id: str, limit: int = 200) -> list[dict]: ...
    def add_chat_exchange(
        self, analysis_id: str, owner_id: str, question: str, answer: dict
    ) -> list[dict] | None: ...


@runtime_checkable
class FileStore(Protocol):
    """Arquivos de cada análise, em diretório por dono."""

    def inputs_dir(self, owner_id: str, analysis_id: str) -> Path: ...
    def outputs_dir(self, owner_id: str, analysis_id: str) -> Path: ...
    def remove_analysis(self, owner_id: str, analysis_id: str) -> None: ...
    def remove_orphans(self, known_ids: set[str], grace_seconds: float = 3600) -> int: ...


@runtime_checkable
class JobQueue(Protocol):
    """Fila de processamento: uma análise por vez, cancelável."""

    def submit(self, owner_id: str, analysis_id: str) -> None: ...
    def cancel(self, analysis_id: str) -> None: ...
    def shutdown(self) -> None: ...

"""Dependências da aplicação, já ligadas aos adaptadores (montadas em main.create_app).

As rotas recebem um `Services` e só enxergam os ports. Trocar SQLite por
Postgres, ou o Gemini por outro modelo, muda quem é construído em
`create_app`, não as rotas.
"""

from dataclasses import dataclass

from .breaker import CircuitBreaker
from .ports import ChatModel, FileStore, IdentityVerifier, JobQueue, Repository
from .settings import Settings
from .uploads import RasterLimits


@dataclass
class Services:
    settings: Settings
    db: Repository
    storage: FileStore
    jobs: JobQueue
    verify_identity: IdentityVerifier
    chat_model: ChatModel | None  # None: só respostas automáticas
    breaker: CircuitBreaker
    raster_limits: RasterLimits

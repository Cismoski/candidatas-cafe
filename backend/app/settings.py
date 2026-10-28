"""Configuração da API via variáveis de ambiente (ver .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Autenticação
    google_client_id: str = Field(min_length=1)
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_ttl_minutes: int = Field(default=60, ge=5, le=24 * 60)
    jwt_issuer: str = "globalwatch-api"
    jwt_audience: str = "globalwatch-web"

    # Quantos proxies confiáveis acrescentam ao X-Forwarded-For (Render: 1).
    # 0 = usa o IP da conexão (desenvolvimento local, sem proxy).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=3)

    # CORS: lista separada por vírgula, ex. "https://app.pages.dev,http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    # Armazenamento
    data_dir: Path = Path("./data")

    # Uploads
    max_upload_mb: int = Field(default=40, ge=1)
    # 1500x1500 px: pico medido ~95 B/px + ~150 MB de imports no subprocesso;
    # cabe nos 512 MB do Render junto com a API (ver README).
    max_raster_dim: int = Field(default=1500, ge=64)
    uploads_per_day: int = Field(default=10, ge=1)
    job_timeout_seconds: int = Field(default=300, ge=10)
    # Análises na fila (todas as contas) acima disso => 503
    max_queued_jobs: int = Field(default=4, ge=1)
    # False só nos testes: roda o pipeline no mesmo processo
    job_isolation: bool = True

    # Chat. Sem chave o assistente usa só as respostas automáticas (determinísticas).
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=15, gt=0, le=60)
    chat_messages_per_day: int = Field(default=30, ge=1)
    # Chamadas simultâneas ao Gemini (cada uma prende uma thread por até o timeout)
    chat_max_concurrent: int = Field(default=4, ge=1, le=16)
    # Circuit breaker do Gemini: N falhas seguidas abrem o circuito por N segundos
    chat_breaker_failures: int = Field(default=3, ge=1)
    chat_breaker_cooldown_seconds: int = Field(default=120, ge=1)

    # Referência independente: COG anual do MapBiomas ({year} é substituído).
    # Vazio desliga a comparação. Lido no subprocesso da análise, com timeout.
    mapbiomas_url: str = (
        "https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection11/"
        "lulc/coverage/brazil_coverage/brazil_coverage-col11_{year}.tif"
    )

    # Retenção
    retention_hours: int = Field(default=24, ge=1)
    retention_sweep_minutes: int = Field(default=15, ge=1)
    # Conta (e-mail/nome) sem login há N dias e sem análises é apagada
    user_retention_days: int = Field(default=30, ge=1)

    @field_validator("mapbiomas_url")
    @classmethod
    def _mapbiomas_url(cls, v: str) -> str:
        """Vazio desliga. Senão: só https e com {year} (o mapa é anual); erro de
        configuração aparece na subida, não escondido como "indisponível"."""
        if not v:
            return v
        if not v.startswith("https://"):
            raise ValueError("MAPBIOMAS_URL deve começar com https://")
        try:
            if v.format(year=2025) == v:
                raise ValueError("MAPBIOMAS_URL precisa conter {year}")
        except (KeyError, IndexError):
            raise ValueError("MAPBIOMAS_URL só pode ter o campo {year}") from None
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "globalwatch.sqlite3"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

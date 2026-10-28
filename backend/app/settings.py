"""Configuração da API via variáveis de ambiente (ver .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Autenticação
    google_client_id: str = Field(min_length=1)
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_ttl_minutes: int = Field(default=60, ge=5, le=24 * 60)
    jwt_issuer: str = "globalwatch-api"
    jwt_audience: str = "globalwatch-web"

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
    # False só nos testes: roda o pipeline no mesmo processo
    job_isolation: bool = True

    # Chat (fase 4)
    chat_messages_per_day: int = Field(default=30, ge=1)

    # Retenção
    retention_hours: int = Field(default=24, ge=1)
    retention_sweep_minutes: int = Field(default=15, ge=1)

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

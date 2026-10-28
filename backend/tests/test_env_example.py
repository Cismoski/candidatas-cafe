"""O .env.example documenta toda configuração e não carrega valores secretos."""

import re
from pathlib import Path

from app.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
FIXED = {"jwt_issuer", "jwt_audience", "job_isolation"}  # constantes, não configuráveis em deploy
FUTURE = {"gemini_api_key"}  # fase 4


def _entries() -> dict[str, str]:
    pairs = (line.strip().split("=", 1) for line in ENV_EXAMPLE.read_text().splitlines())
    return {
        k.lower(): v
        for k, v in (p for p in pairs if len(p) == 2 and re.fullmatch(r"[A-Z_]+", p[0]))
    }


def test_env_example_exists_and_matches_settings():
    keys = set(_entries())
    fields = set(Settings.model_fields)
    assert keys - fields - FUTURE == set()
    assert fields - keys - FIXED == set()


def test_env_example_has_no_secret_values():
    entries = _entries()
    for secret in ("google_client_id", "jwt_secret", "gemini_api_key"):
        assert entries[secret] == "", secret

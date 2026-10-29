"""Value objects: valores validados na criação e imutáveis depois.

Cada um concentra uma regra que antes ficava espalhada pelas rotas ou pelo
chat. Quem recebe um `AnalysisId` não precisa conferir de novo se é um UUID;
quem formata uma `AcquisitionDate` não quebra com data inexistente.
Os identificadores e a chave de idempotência são `str` validadas: entram no
SQLite e em caminhos de arquivo sem conversão.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime

MAX_TITLE_CHARS = 80
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_\-]{8,64}")


class AnalysisId(str):
    """UUID de uma análise, na forma canônica (minúsculas, com hífens).

    Também vira nome de diretório: só passa o que `uuid.UUID` aceita, então não
    há "../" nem separador de caminho.
    """

    __slots__ = ()

    def __new__(cls, raw: str) -> "AnalysisId":
        try:
            canonical = str(uuid.UUID(raw))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("identificador de análise inválido") from None
        return super().__new__(cls, canonical)

    @classmethod
    def new(cls) -> "AnalysisId":
        return cls(str(uuid.uuid4()))


class IdempotencyKey(str):
    """Chave enviada no header Idempotency-Key: 8 a 64 caracteres [A-Za-z0-9_-]."""

    __slots__ = ()

    def __new__(cls, raw: str) -> "IdempotencyKey":
        if not isinstance(raw, str) or not _IDEMPOTENCY_KEY.fullmatch(raw):
            raise ValueError("Idempotency-Key inválida (8-64 caracteres [A-Za-z0-9_-]).")
        return super().__new__(cls, raw)


@dataclass(frozen=True)
class AnalysisTitle:
    """Título de uma análise: espaços normalizados e no máximo 80 caracteres.

    Vazio vira o nome do arquivo enviado (cortado em 80) ou "Análise".
    """

    value: str

    def __post_init__(self) -> None:
        if (
            not self.value
            or len(self.value) > MAX_TITLE_CHARS
            or self.value != " ".join(self.value.split())
        ):
            raise ValueError("título vazio, longo ou com espaços não normalizados")

    @classmethod
    def from_form(cls, raw: object, filename: str | None) -> "AnalysisTitle":
        if not isinstance(raw, str) or len(raw) > MAX_TITLE_CHARS:
            raise ValueError(f"Título deve ter no máximo {MAX_TITLE_CHARS} caracteres.")
        clean = " ".join(raw.split())
        if not clean:
            clean = " ".join((filename or "").split())[:MAX_TITLE_CHARS].strip() or "Análise"
        return cls(clean)


@dataclass(frozen=True)
class AcquisitionDate:
    """Data de aquisição da cena, ou desconhecida.

    Vem do summary.json, que pode ser antigo ou ter uma tag inválida: em vez de
    lançar exceção ao formatar (o que derrubava o chat com 500), uma data que
    não existe vira "desconhecida".
    """

    day: date | None

    @classmethod
    def parse(cls, raw: object) -> "AcquisitionDate":
        if not isinstance(raw, str):
            return cls(None)
        try:
            return cls(datetime.fromisoformat(raw.replace("Z", "+00:00")).date())
        except ValueError:
            return cls(None)

    @property
    def known(self) -> bool:
        return self.day is not None

    def iso(self) -> str | None:
        """AAAA-MM-DD, ou None (no contexto do modelo, "sem data")."""
        return self.day.isoformat() if self.day else None

    def br(self) -> str:
        """DD/MM/AAAA para o usuário, ou "data desconhecida"."""
        return self.day.strftime("%d/%m/%Y") if self.day else "data desconhecida"

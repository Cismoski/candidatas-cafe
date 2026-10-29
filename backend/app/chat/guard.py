"""Checagem da resposta do modelo: números que não estão no resultado e afirmações de acerto."""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .text import _norm

FREE_INTEGERS = set(range(0, 13))


# --- checagem de números -----------------------------------------------------------------
# Número isolado: não pode estar colado a letra/dígito antes ("p95", "B04",
# "S2B_T23KLS"), mas pode ter unidade colada depois ("155ha", "1ª").
_NUMBER = re.compile(
    r"(?<![\w.,])(-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?)(?!\d)(?![.,]\d)"
    r"(\s*(?:%|por\s*cento)|\s+(?:mil|milh[õo]es|milh[ãa]o)\b)?",
    re.IGNORECASE,
)
_MAX_DIGITS = 15  # acima disso não há valor no contexto (e float() vira inf)
# Por extenso acima de doze (0..12 são livres na prosa; ver FREE_INTEGERS)
_NUMBER_WORDS = re.compile(
    r"\b(?:treze|quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|"
    r"quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|"
    r"(?:duz|trez|quatroc|quinh|seisc|setec|oitoc|novec)ent[oa]s|"
    r"mil|milhao|milhoes|bilhao|bilhoes)\b"
)
_ACCURACY = re.compile(r"acurac|precisao|confiab|confiav|kappa|\bf1\b|acerto|exatidao")
_ACCURACY_ADJ = re.compile(
    r"(?:alta|elevada|grande|boa|otima|excelente)\s+(?:acurac|precisao|confiab|exatidao)"
    r"|\b(?:certamente|com certeza|sem duvida|garantidamente)\b"
)
# Afirmações qualitativas de acerto ou certeza; valem só sem negação logo antes
# ("não foram confirmadas em campo" é honesto).
_QUALITY_CLAIM = re.compile(
    r"\bacert(?:a|am|ou|aram|ando|ividade)\b"
    r"|\bcorretamente\b"
    r"|\b(?:muito|altamente|bastante|extremamente|totalmente)\s+"
    r"(?:confiave|precis|exat|corret|segur)"
    r"|\b(?:e|sao|foi|foram|esta|estao)\s+(?:\w+\s+)?confiave(?:l|is)\b"
    r"|\b(?:resultado|metodo|classificacao|mapa|mapeamento|identificacao)\w*\s+"
    r"(?:\w+\s+){0,2}(?:e|sao|foi|esta)\s+(?:\w+\s+){0,1}(?:precis[oa]s?|exat[oa]s?)\b"
    # "precisam ser confirmadas" é a ressalva pedida; só a afirmação conta
    r"|\b(?:e|sao|foi|foram|esta|estao)\s+(?:\w+\s+)?confirmad[ao]s?\b"
    # "separa pasto e café" não afirma nada: "é café" precisa de um sujeito do resultado
    r"|(?:\bsao|\b(?:area|poligono|talh|candidat|mancha)\w*\s+(?:\w+\s+){0,2}e)"
    r"\s+(?:de\s+)?cafe\b(?!\s+(?:em potencial|potencial|candidat))"
)
# Negação ou condição nas 3 palavras antes da afirmação ("se o método acerta")
_NEGATION = {"nao", "nem", "sem", "nada", "nenhum", "nenhuma", "jamais", "nunca", "se"}
_NEGATION_WORDS = 3
# Frações por extenso também são números ("metade das candidatas é pasto")
_FRACTION_WORDS = re.compile(
    r"\b(?:metade(?=\s+d(?:[aoe]|as|os)\b)|(?:um|dois|1|2)\s+tercos?|(?:um|tres|1|3)\s+quartos?\s+d)"
)
_SMALL_WORDS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
}  # fmt: skip
_COUNT = re.compile(r"(?<![\w.,])(\d+|" + "|".join(_SMALL_WORDS) + r")\s+(?:poligonos|talhoes)\b")
# Contagem dada como total ("são 7 polígonos"); "os 3 maiores polígonos" é subconjunto
_TOTAL_WORDS = {"sao", "ha", "foram", "total", "encontrei", "encontrados", "existem", "tem"}
_HECTARE = re.compile(r"\s*(?:ha\b|hectares?\b)", re.IGNORECASE)
# id da cena e nome da fonte têm dígitos que não são medidas ("Coleção 11", "30 m")
_SKIP_KEYS = {"cena", "fonte"}


def _numbers_in(
    value, key: str = "", percent: bool = False, area: bool = False
) -> Iterable[tuple[float, bool, bool]]:
    """(valor, é_percentual, é_área) de tudo que é número no contexto. Chave
    terminada em "percentual" ou "_ha" marca o valor e tudo o que estiver
    aninhado nela."""
    if isinstance(value, bool) or value is None or key in _SKIP_KEYS:
        return
    percent = percent or key.endswith("percentual")
    area = area or key.endswith("_ha")
    if isinstance(value, int | float):
        if math.isfinite(value):
            yield abs(float(value)), percent, area
    elif isinstance(value, str):
        for n in parse_numbers(value):
            for v in n.readings:
                yield v, n.kind is Kind.PERCENT, n.kind is Kind.AREA
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _numbers_in(v, str(k), percent, area)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _numbers_in(v, key, percent, area)


class Kind(StrEnum):
    """Tipo de uma quantidade: só se compara com valores do mesmo tipo."""

    PLAIN = "simples"
    PERCENT = "percentual"
    AREA = "area"  # número seguido de "ha"/"hectares"


@dataclass(frozen=True)
class Quantity:
    """Número citado na resposta, com as leituras possíveis (sempre em valor absoluto)."""

    token: str
    readings: tuple[float, ...]
    kind: Kind = Kind.PLAIN

    def tolerance(self, reading: float) -> float:
        """Meia unidade da última casa escrita: "0,55" casa com 0,546; "0,5" com 0,46."""
        return 0.5 * 10 ** -_decimals(self.token.split(" ")[0], reading) + 1e-9

    def is_free_integer(self, reading: float) -> bool:
        return self.kind is Kind.PLAIN and reading == int(reading) and int(reading) in FREE_INTEGERS


@dataclass(frozen=True)
class Allowed:
    """Valores do contexto, por tipo. Percentual na resposta só casa com valor
    percentual ("90%" não se apoia nos 90 polígonos) e número seguido de "ha" só
    casa com área ("0,66 ha" não se apoia no NDVI 0,66). `counts` são as
    quantidades de polígonos que o contexto informa."""

    plain: frozenset[float] = frozenset()
    percent: frozenset[float] = frozenset()
    area: frozenset[float] = frozenset()
    counts: frozenset[int] = frozenset()

    def supports(self, q: Quantity) -> bool:
        """Alguma leitura de `q` é inteiro livre ou arredondamento de um valor do mesmo tipo?"""
        pool = {Kind.PERCENT: self.percent, Kind.AREA: self.area}.get(q.kind, self.plain)
        return any(
            q.is_free_integer(x) or any(abs(x - a) <= q.tolerance(x) for a in pool)
            for x in q.readings
        )

    def supports_count(self, n: int, as_total: bool) -> bool:
        """Contagem de polígonos: dada como total, tem de bater; como subconjunto
        ("os 3 maiores"), basta não passar do total."""
        return n in self.counts or (not as_total and n <= max(self.counts, default=0))


def allowed_numbers(context: dict) -> Allowed:
    plain, percent, area = set(), set(), set()
    for v, is_pct, is_area in _numbers_in(context):
        (percent if is_pct else plain).add(v)
        if is_area and not is_pct:
            area.add(v)
    counts = {
        n
        for n in (
            (context.get("resultado") or {}).get("poligonos_candidatos"),
            context.get("total_de_poligonos_no_resultado"),
            len(context.get("poligonos") or []),
        )
        if isinstance(n, int)
    }
    return Allowed(frozenset(plain), frozenset(percent), frozenset(area), frozenset(counts))


def parse_numbers(text: str) -> list[Quantity]:
    """Números do texto com as leituras possíveis (sempre em valor absoluto).

    "2.620,20" -> 2620.2; "0,55" -> 0.55; "2.620" é ambíguo (milhar pt-BR ou
    decimal en) e vale qualquer das duas leituras; "3 mil" -> 3000.
    Token longo demais vira leitura vazia (sempre recusado).
    """
    found = []
    for m in _NUMBER.finditer(text):
        tok, suffix = m.group(1), (m.group(2) or "").strip().lower()
        t = tok.lstrip("-")
        if sum(c.isdigit() for c in t) > _MAX_DIGITS:
            readings = []
        elif "," in t:
            readings = [float(t.replace(".", "").replace(",", "."))]
        elif re.fullmatch(r"\d{1,3}\.\d{3}", t):
            readings = [float(t.replace(".", "")), float(t)]  # "2.620": 2620 ou 2,62
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}", t):
            readings = [float(t.replace(".", ""))]  # "3.272.300": só milhar
        else:
            readings = [float(t)]
        if suffix.startswith("mil"):
            mult = 1e3 if suffix == "mil" else 1e6
            readings = [x * mult for x in readings]
            tok = f"{tok} {suffix}"
        if suffix.startswith(("%", "por")):
            kind, tok = Kind.PERCENT, tok + "%"
        elif _HECTARE.match(text, m.end()):
            kind = Kind.AREA
        else:
            kind = Kind.PLAIN
        found.append(Quantity(tok, tuple(readings), kind))
    return found


def _decimals(tok: str, reading: float) -> int:
    t = tok.lstrip("-").rstrip("%")
    if "," in t:
        return len(t.split(",")[1])
    if "." in t and reading != float(t.replace(".", "")):
        return len(t.split(".")[1])
    return 0


def unsupported_numbers(reply: str, allowed: Allowed) -> list[str]:
    """Números da resposta que não são arredondamento de nenhum valor do contexto
    do mesmo tipo, mais contagens de polígonos que não batem e frações por extenso."""
    bad = [q.token for q in parse_numbers(reply) if not allowed.supports(q)]
    # "3 mil" e "5 por cento" já foram lidos acima; o resto por extenso é recusado
    norm = _norm(reply)
    words = _NUMBER.sub(" ", norm)
    bad += [m.group(0) for m in _NUMBER_WORDS.finditer(words)]
    bad += [m.group(0) for m in _FRACTION_WORDS.finditer(norm)]
    bad += re.findall(r"\d(?:[.,]\d+)?e[+-]?\d+", norm)  # notação científica: "1e3"
    # "7 polígonos" ou "sete talhões": inteiro pequeno não é livre quando é contagem
    for m in _COUNT.finditer(norm):
        n = int(m.group(1)) if m.group(1).isdigit() else _SMALL_WORDS[m.group(1)]
        as_total = bool(_TOTAL_WORDS & set(re.findall(r"\w+", norm[: m.start()])[-2:]))
        if not allowed.supports_count(n, as_total):
            bad.append(m.group(0))
    return bad


def accuracy_claim(reply: str) -> bool:
    """Afirma acurácia/confiabilidade? (número ou "%" a até 40 caracteres do termo,
    adjetivo como "alta precisão", "certamente", ou afirmação qualitativa como "o
    método acerta", "são confiáveis", "são café" sem negação antes). Falso
    positivo é barato: só troca a resposta pela automática."""
    t = _norm(reply)
    if _ACCURACY_ADJ.search(t):
        return True
    for m in _QUALITY_CLAIM.finditer(t):
        before = re.findall(r"\w+", t[: m.start()])[-_NEGATION_WORDS:]
        if not _NEGATION.intersection(before):
            return True
    for m in _ACCURACY.finditer(t):
        window = t[max(0, m.start() - 40) : m.end() + 40]
        if re.search(r"\d|%|por cento", window):
            return True
    return False

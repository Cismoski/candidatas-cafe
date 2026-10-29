"""Respostas automáticas: determinísticas, por palavras-chave e templates sobre o summary."""

import re

from ..values import AcquisitionDate
from .context import mentioned_polygon_ids
from .text import _norm


def _ha(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " ha"


def _num(v: float | None, nd: int = 2) -> str:
    return "sem valor" if v is None else f"{v:.{nd}f}".replace(".", ",")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + "%"


def _date_br(raw: object) -> str:
    return AcquisitionDate.parse(raw).br()


def _cls(summary: dict, key: str) -> float:
    return summary["results"]["class_areas"][key]["area_ha"]


def introduction(summary: dict) -> str:
    r, m, inp = summary["results"], summary["method"], summary["inputs"]
    date = _date_br(inp["primary"].get("acquired_utc"))
    if r["candidate_polygons"] == 0:
        head = (
            f"Na imagem de {date}, nenhuma área passou em todas as regras: "
            "não há candidatas a café nesta cena."
        )
    else:
        head = (
            f"Na imagem de {date}, encontrei {r['candidate_polygons']} "
            f"{'polígono candidato' if r['candidate_polygons'] == 1 else 'polígonos candidatos'} "
            f"a café, somando {_ha(r['candidate_area_ha'])}, ou {_pct(r['candidate_fraction_of_analysed'])} "
            f"dos {_ha(r['analysed_area_ha'])} analisados."
        )
    how = (
        f"Foram excluídos água ({_ha(_cls(summary, 'water'))}), solo exposto ou vegetação rala "
        f"({_ha(_cls(summary, 'low_vegetation'))}) e dossel fechado de mata ou eucalipto "
        f"({_ha(_cls(summary, 'dense_canopy'))}, NDVI a partir de "
        f"{_num(m['dense_canopy_ndvi_threshold'], 3)})."
    )
    temporal = (
        "A segunda data foi usada para confirmar vegetação perene."
        if m["mode"] == "two_dates"
        else "Só uma data foi enviada, então a estabilidade ao longo do tempo não foi verificada."
    )
    caveat = (
        "São áreas potenciais, não confirmadas em campo, então não há acurácia a informar. "
        "Pergunte sobre áreas, polígonos, índices, método ou limitações."
    )
    return " ".join([head, how, temporal, caveat])


def reference_answer(ref: dict) -> str:
    classes = ", ".join(
        f"{k} {_pct(v)}" for k, v in list(ref["candidates_by_reference_class"].items())[:3]
    )
    on = ref["candidates_on_reference_coffee"]
    return (
        f"O MapBiomas {ref['year']} mapeia {_ha(ref['reference_coffee_ha'])} de café nesta área. "
        + (
            f"{_pct(on)} das candidatas caem sobre esse café (IoU {_num(ref['iou'], 3)}); "
            f"pelo MapBiomas, as candidatas são sobretudo: {classes}. "
            if on is not None
            else ""
        )
        + "É concordância entre dois mapas, não acurácia."
    )


def automatic_answer(question: str, summary: dict) -> str:
    q = _norm(question)
    r, m, inp = summary["results"], summary["method"], summary["inputs"]
    polys = r["polygons"]
    by_id = {p["id"]: p for p in polys}

    ids = mentioned_polygon_ids(question)
    if ids:
        pid = ids[0]
        p = by_id.get(pid)
        if p is None:
            return (
                f"Não existe polígono nº {pid} nesta análise; os polígonos vão de 1 a {len(polys)}."
                if polys
                else "Esta análise não tem polígonos candidatos."
            )
        extra = (
            f", NDVI médio na segunda data {_num(p['ndvi_other_date_mean'])}"
            if p.get("ndvi_other_date_mean") is not None
            else ""
        )
        return (
            f"O polígono nº {pid} tem {_ha(p['area_ha'])}, NDVI médio {_num(p['ndvi_mean'])}, "
            f"NDWI médio {_num(p['ndwi_mean'])} e SAVI médio {_num(p['savi_mean'])}{extra}."
        )
    ref = summary.get("reference") or {}
    # só pedidos explícitos: "compare com a segunda data" ou "data de referência" não são isso
    if re.search(r"mapbiomas|concordan|concorda com", q):
        if ref.get("status") != "ok":
            return "A comparação com o MapBiomas não está disponível nesta análise."
        return reference_answer(ref)
    if re.search(r"acurac|precis|confiab|confiav|validad|certeza|acert", q):
        extra = (
            " O que existe é a concordância com o MapBiomas: " + reference_answer(ref)
            if ref.get("status") == "ok"
            else ""
        )
        return (
            "Não há acurácia a informar: não existem amostras de campo para comparar. O resultado "
            "indica áreas candidatas por regras espectrais, que precisam de conferência em campo "
            "ou com imagens de maior resolução." + extra
        )
    rank = re.search(r"\b(maior|menor)(es)?\b", q)
    # "a mata é maior que o café?" é sobre classes, não ranking de polígonos
    if rank and not re.search(r"agua|mata|floresta|dossel|eucalipt|solo|pasto", q):
        if not polys:
            return "Esta análise não tem polígonos candidatos."
        word = rank.group(1)
        than = re.search(r"(maior|menor)(?:es)? (?:do )?que (\d+(?:[.,]\d+)?)", q)
        if than:
            limit = float(than.group(2).replace(",", "."))
            n = sum(
                (p["area_ha"] > limit) if than.group(1) == "maior" else (p["area_ha"] < limit)
                for p in polys
            )
            return (
                f"{n} de {len(polys)} polígonos candidatos têm área {than.group(1)} que "
                f"{_ha(limit)}."
            )
        idx = next((i for i in ("ndvi", "ndwi", "savi") if i in q), None)
        field = f"{idx}_mean" if idx else "area_ha"
        pick = max if word == "maior" else min
        p = pick(polys, key=lambda x: x[field])
        if idx:
            return (
                f"O polígono com {word} {idx.upper()} médio é o nº {p['id']}: "
                f"{_num(p[field])}, com {_ha(p['area_ha'])}."
            )
        return f"O {word} polígono candidato é o nº {p['id']}, com {_ha(p['area_ha'])} e NDVI médio {_num(p['ndvi_mean'])}."
    if re.search(r"segunda|temporal|outra data|duas datas|estabil", q):
        if m["mode"] != "two_dates":
            return "Só uma data foi enviada, então a estabilidade temporal não foi verificada."
        shift = m.get("temporal_ndvi_shift")
        seasonal = (
            f" Antes, foi descontada a variação sazonal da vegetação da cena: NDVI "
            f"{'+' if shift >= 0 else '−'}{_num(abs(shift), 3)} entre as datas."
            if shift is not None
            else ""
        )
        return (
            f"A segunda data ({_date_br((inp.get('secondary') or {}).get('acquired_utc'))}) rejeitou "
            f"{_ha(r['temporal_rejected_ha'])} por mudança de NDVI; {_ha(r['temporal_unverified_ha'])} "
            f"ficaram sem verificação por nuvem ou falta de cobertura.{seasonal}"
        )
    for idx in ("ndvi", "ndwi", "savi"):
        if idx in q:
            s = r["index_stats"].get(idx)
            if not s:
                return f"O {idx.upper()} não está nas estatísticas desta análise."
            a, c = s["analysed_land"], s["candidates"]
            if not c or not a:
                return (
                    f"{idx.upper()} médio na área analisada: {_num((a or {}).get('mean'))}. "
                    "Não há candidatas, então não há estatística delas."
                )
            return (
                f"{idx.upper()} médio: {_num(c['mean'])} nas candidatas e {_num(a['mean'])} na área "
                f"analisada (mediana {_num(c['median'])} e {_num(a['median'])}; faixa p05 a p95 das "
                f"candidatas de {_num(c['p05'])} a {_num(c['p95'])})."
            )
    if re.search(r"agua|rio|lago|represa", q):
        return f"Água ou alta umidade: {_ha(_cls(summary, 'water'))} (NDWI acima de {_num(m['parameters'].get('rules', {}).get('ndwi_max', 0.0), 2)})."
    if re.search(r"mata|floresta|dossel|eucalipt", q):
        return (
            f"Dossel fechado (mata ou eucalipto): {_ha(_cls(summary, 'dense_canopy'))}, definido por NDVI a "
            f"partir de {_num(m['dense_canopy_ndvi_threshold'], 3)} ({m['dense_canopy_threshold_source']})."
        )
    if re.search(r"solo|pasto|rala|expost", q):
        return f"Solo exposto ou vegetação rala: {_ha(_cls(summary, 'low_vegetation'))}."
    if re.search(r"nuve|scl|mascara|sombra", q):
        used = "foi aplicada" if inp["scl_used"] else "não foi enviada"
        return f"A máscara de qualidade (SCL) {used}; {_ha(_cls(summary, 'masked_quality'))} foram excluídos por ela."
    if re.search(r"poligon|talh", q) and not re.search(r"hectar|\bha\b", q):
        return f"São {r['candidate_polygons']} polígonos candidatos, somando {_ha(r['candidate_area_ha'])}."
    if re.search(r"area|hectar|\bha\b|tamanho|total|quant", q):
        return (
            f"A área candidata a café é de {_ha(r['candidate_area_ha'])}, {_pct(r['candidate_fraction_of_analysed'])} "
            f"dos {_ha(r['analysed_area_ha'])} analisados."
        )
    if re.search(r"data|quando|que dia|qual dia|imagem|cena|satelit", q):
        return f"A imagem principal é de {_date_br(inp['primary'].get('acquired_utc'))}, cena {inp['primary'].get('source_item') or 'sem identificador'}, pixel de {_num(inp['primary']['pixel_size_m'][0], 0)} m."
    if re.search(r"metodo|como|criterio|regra|limiar|otsu|classific|calcul", q):
        return (
            f"{m['description']} O limiar de dossel fechado foi NDVI {_num(m['dense_canopy_ndvi_threshold'], 3)} "
            f"({m['dense_canopy_threshold_source']})."
        )
    if re.search(r"limitac|erro|problema|confund|falh", q):
        return " ".join(summary["limitations"][:3])
    return (
        "Posso responder sobre a área candidata, a quantidade e o tamanho dos polígonos, um "
        "polígono específico (ex.: polígono nº 3), NDVI, NDWI e SAVI, água, mata, solo exposto, "
        "a data da imagem, o método e as limitações."
    )

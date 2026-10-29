"""Assistente da análise: contexto fechado, checagem de números e respostas automáticas.

Três camadas para "responder só com os números do processamento":
1. Contexto fechado: o modelo recebe apenas um extrato do summary.json.
2. Prompt de sistema com as regras (usar só o contexto, dizer quando não sabe,
   nunca afirmar acurácia, tratar a pergunta como dado).
3. Checagem na saída (`guard.unsupported_numbers` e `guard.accuracy_claim`): todo número
   da resposta tem de ser um arredondamento de algum valor do contexto do
   mesmo tipo (percentual com percentual, "N ha" com área, "N polígonos" com
   a contagem real); inteiros de 0 a 12 soltos na prosa passam. Número por
   extenso acima de doze, fração por extenso ("metade") e notação científica
   são recusados, assim como acurácia perto de um número e afirmação
   qualitativa de acerto ou certeza ("o método acerta", "são café") sem
   negação antes. Falhou, a resposta do modelo é descartada e vale a resposta
   automática. É heurística: pega número inventado, não pega frase errada com
   número certo (ex.: atribuir a área de um polígono a outro, ou trocar o
   sinal de um índice, porque a comparação é em valor absoluto).

A resposta automática (`automatic_answer`) é determinística, feita por regras de
palavras-chave e templates sobre o mesmo summary. Ela é usada sem chave, com o
Gemini falhando ou com o circuito aberto, e também na mensagem de abertura.

Módulos: `context` (extrato e prompt), `guard` (checagem), `answers` (respostas
automáticas), `assistant` (orquestração com o breaker).
"""

from .answers import automatic_answer, introduction, reference_answer
from .assistant import (
    NOTICE_FAILED,
    NOTICE_GUARD,
    NOTICE_NO_MODEL,
    NOTICE_OPEN,
    NOTICE_SKIPPED,
    respond,
)
from .context import (
    HISTORY_MESSAGES,
    MAX_MESSAGE_CHARS,
    TOP_POLYGONS,
    build_context,
    mentioned_polygon_ids,
    system_prompt,
)

__all__ = [
    "HISTORY_MESSAGES",
    "MAX_MESSAGE_CHARS",
    "NOTICE_FAILED",
    "NOTICE_GUARD",
    "NOTICE_NO_MODEL",
    "NOTICE_OPEN",
    "NOTICE_SKIPPED",
    "TOP_POLYGONS",
    "automatic_answer",
    "build_context",
    "introduction",
    "mentioned_polygon_ids",
    "reference_answer",
    "respond",
    "system_prompt",
]

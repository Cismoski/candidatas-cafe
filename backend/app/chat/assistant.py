"""Orquestração: Gemini quando possível, resposta automática quando não."""

from .answers import automatic_answer
from .context import HISTORY_MESSAGES, build_context, system_prompt
from .guard import accuracy_claim, allowed_numbers, unsupported_numbers

# --- orquestração ------------------------------------------------------------------------------
NOTICE_NO_MODEL = "O assistente de IA não está configurado neste servidor."
NOTICE_OPEN = "O assistente de IA está instável; volta a ser usado em alguns minutos."
NOTICE_FAILED = "O assistente de IA não respondeu a tempo."
NOTICE_SKIPPED = "O assistente de IA está ocupado ou não gerou resposta para esta pergunta."
NOTICE_GUARD = (
    "A resposta da IA citou números ou acurácia que não estão no processamento e foi descartada."
)


def respond(question: str, summary: dict, history: list, model, breaker) -> dict:
    """Responde com o Gemini quando possível; senão, pela resposta automática.

    Ordem: sem modelo -> automática. Circuito aberto -> automática sem chamar.
    Falha do serviço (rede, timeout, 429, 5xx, chave) -> conta no breaker -> automática.
    Sem veredito sobre o serviço (ocupado, resposta vazia/bloqueada/cortada, ou
    descartada pela checagem) -> libera a sonda sem contar falha -> automática.
    Qualquer saída depois de `allow()` registra um veredito ou libera a sonda
    (finally): sonda presa deixaria o Gemini desligado até reiniciar o processo.
    """
    from ..llm import LLMError, LLMSkipped, Turn

    def automatic(notice: str) -> dict:
        return {
            "content": automatic_answer(question, summary),
            "source": "automatica",
            "notice": notice,
        }

    if model is None:
        return automatic(NOTICE_NO_MODEL)
    if not breaker.allow():
        return automatic(NOTICE_OPEN)
    verdict = False
    try:
        recent = history[-HISTORY_MESSAGES:]
        context = build_context(summary, question, [h["content"] for h in recent])
        turns = [Turn(h["role"], h["content"]) for h in recent]
        try:
            reply = model.generate(system_prompt(context), turns, question)
        except LLMSkipped:
            return automatic(NOTICE_SKIPPED)
        except LLMError:
            breaker.record_failure()
            verdict = True
            return automatic(NOTICE_FAILED)
        except Exception:
            breaker.record_failure()
            verdict = True
            raise
        if unsupported_numbers(reply, allowed_numbers(context)) or accuracy_claim(reply):
            return automatic(NOTICE_GUARD)
        breaker.record_success()
        verdict = True
        return {"content": reply, "source": "gemini", "notice": None}
    finally:
        if not verdict:
            breaker.release()

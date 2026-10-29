"""Cliente do Gemini (google-genai). A chave só existe no backend.

O que vai para o Google: o prompt de sistema, o extrato de números do
summary.json da análise e as últimas mensagens da conversa. Nunca nome,
e-mail ou id do usuário. No free tier o Google pode usar prompts e respostas
para melhorar produtos e revisores humanos podem lê-los (termos "Unpaid
Services"); por isso o contexto é só numérico. Ver README > Assistente.
"""

import logging
import threading

from .ports import LLMError, LLMSkipped, Turn

log = logging.getLogger("cafe.llm")


# Dicas fixas para erros de configuração (nunca o texto do Google, que pode ecoar o prompt)
_HINTS = {
    400: " (requisição recusada; conferir GEMINI_MODEL)",
    402: " (projeto sem crédito; usar chave de um projeto no nível gratuito)",
    403: " (chave sem permissão para a API)",
    404: " (modelo indisponível para esta chave; conferir GEMINI_MODEL)",
    429: " (cota do Gemini esgotada)",
}


class GeminiChat:
    def __init__(self, api_key: str, model: str, timeout_s: float, max_concurrent: int = 4):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
        # A rota é síncrona: cada chamada prende uma thread do pool do anyio
        # (40, compartilhadas com login, lista e downloads). Acima deste limite a
        # pergunta vai para a resposta automática em vez de esperar.
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_s * 1000),  # ms
                # Sem retry interno: quem decide é o circuit breaker. Retry
                # aqui multiplicaria o tempo de espera e o consumo de cota.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate(self, system: str, history: list[Turn], message: str) -> str:
        t = self._types
        contents = [
            t.Content(
                role="model" if h.role == "assistant" else "user", parts=[t.Part(text=h.text)]
            )
            for h in history
        ]
        contents.append(t.Content(role="user", parts=[t.Part(text=message)]))
        if not self._slots.acquire(blocking=False):
            raise LLMSkipped("ocupado")
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=t.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.2,  # respostas factuais, pouca variação
                    max_output_tokens=600,
                    automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as e:  # APIError, httpx.TimeoutException, erros de rede...
            # Só o tipo/código vai para o log: a mensagem pode ecoar o prompt
            code = getattr(e, "code", None)
            log.warning(
                "falha no Gemini: %s %s%s", type(e).__name__, code or "", _HINTS.get(code, "")
            )
            raise LLMError(type(e).__name__) from None
        finally:
            self._slots.release()
        finish = resp.candidates[0].finish_reason if resp.candidates else None
        if finish == t.FinishReason.MAX_TOKENS:
            raise LLMSkipped("resposta cortada")  # frase pela metade não vai para o usuário
        text = (resp.text or "").strip()
        if not text:
            # prompt bloqueado (prompt_feedback), candidato filtrado etc.
            raise LLMSkipped("resposta vazia")
        return text

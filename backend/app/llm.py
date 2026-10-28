"""Cliente do Gemini (google-genai). A chave só existe no backend.

O que vai para o Google: o prompt de sistema, o extrato de números do
summary.json da análise e as últimas mensagens da conversa. Nunca nome,
e-mail ou id do usuário. No free tier o Google pode usar prompts e respostas
para melhorar produtos e revisores humanos podem lê-los (termos "Unpaid
Services"); por isso o contexto é só numérico. Ver README > Assistente.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("globalwatch.llm")


class LLMError(Exception):
    """Falha ao obter resposta (rede, timeout, 429, 5xx, chave inválida, resposta vazia)."""


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str


class ChatModel(Protocol):
    def generate(self, system: str, history: list[Turn], message: str) -> str: ...


class GeminiChat:
    def __init__(self, api_key: str, model: str, timeout_s: float):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
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
            log.warning("falha no Gemini: %s %s", type(e).__name__, code or "")
            raise LLMError(type(e).__name__) from None
        text = (resp.text or "").strip()
        if not text:
            # bloqueio de segurança, MAX_TOKENS sem texto etc.
            raise LLMError("resposta vazia")
        return text

"""Cliente do Gemini sem rede: configuração, mapeamento de papéis e classificação dos erros."""

import threading
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types

from app.llm import GeminiChat, LLMError, LLMSkipped, Turn


def resp(text="ok", finish=types.FinishReason.STOP, candidates=True):
    cands = [SimpleNamespace(finish_reason=finish)] if candidates else None
    return SimpleNamespace(text=text, candidates=cands)


@pytest.fixture
def gc(monkeypatch):
    g = GeminiChat("chave-falsa", "gemini-teste", 15, max_concurrent=1)
    calls = []

    def fake(**kw):
        calls.append(kw)
        out = g.next
        if isinstance(out, BaseException):
            raise out
        return out

    monkeypatch.setattr(g._client.models, "generate_content", fake)
    g.next, g.calls = resp(), calls
    return g


def test_http_options_no_retry_and_timeout_in_ms(gc):
    opts = gc._client._api_client._http_options
    assert opts.timeout == 15_000 and opts.retry_options.attempts == 1


def test_roles_and_config(gc):
    out = gc.generate("SYS", [Turn("user", "a"), Turn("assistant", "b")], "c")
    assert out == "ok"
    kw = gc.calls[0]
    assert [c.role for c in kw["contents"]] == ["user", "model", "user"]
    assert kw["contents"][-1].parts[0].text == "c"
    cfg = kw["config"]
    assert cfg.system_instruction == "SYS" and cfg.automatic_function_calling.disable


@pytest.mark.parametrize(
    "exc",
    [
        errors.APIError(
            429, {"error": {"message": "eco do prompt", "status": "RESOURCE_EXHAUSTED"}}
        ),
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("rede"),
    ],
)
def test_service_errors_are_llm_error_and_do_not_leak_message(gc, exc, caplog):
    gc.next = exc
    with pytest.raises(LLMError) as e:
        gc.generate("s", [], "m")
    assert not isinstance(e.value, LLMSkipped)  # conta no breaker
    assert "eco do prompt" not in caplog.text and "eco do prompt" not in str(e.value)


@pytest.mark.parametrize(
    "r",
    [
        resp(text=None, candidates=False),  # prompt bloqueado
        resp(text="   "),
        resp(text="frase pela me", finish=types.FinishReason.MAX_TOKENS),
    ],
)
def test_empty_blocked_or_cut_is_skipped(gc, r):
    gc.next = r
    with pytest.raises(LLMSkipped):
        gc.generate("s", [], "m")


def test_busy_is_skipped_and_slot_released(gc):
    started, go = threading.Event(), threading.Event()

    def slow(**kw):
        started.set()
        go.wait(5)
        return resp()

    gc._client.models.generate_content = slow
    t = threading.Thread(target=gc.generate, args=("s", [], "m"))
    t.start()
    started.wait(5)
    with pytest.raises(LLMSkipped):  # max_concurrent=1: a segunda não espera
        gc.generate("s", [], "m")
    go.set()
    t.join(5)
    assert gc.generate("s", [], "m") == "ok"  # vaga devolvida


def test_slot_released_after_error(gc):
    gc.next = httpx.ReadTimeout("t")
    for _ in range(3):
        with pytest.raises(LLMError):
            gc.generate("s", [], "m")
    gc.next = resp()
    assert gc.generate("s", [], "m") == "ok"

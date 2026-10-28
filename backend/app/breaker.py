"""Circuit breaker para a chamada ao Gemini.

Por quê: com o Gemini fora do ar, em 429 (cota do free tier esgotada) ou com
a chave inválida, cada pergunta esperaria o timeout inteiro (15 s) prendendo
uma thread da API, para no fim cair na resposta automática de qualquer jeito.
Depois de `failure_threshold` falhas SEGUIDAS o circuito abre: por
`cooldown_s` segundos o chat responde direto pelo modo automático, sem chamar
o Gemini. Passado esse tempo ele fica "meio aberto": UMA requisição de teste
passa; sucesso fecha o circuito, falha reabre por mais um período.

Estado em memória do processo: o deploy roda 1 worker numa instância (ver
README). Com réplicas, cada uma teria o próprio circuito, o que é aceitável
para um breaker (no pior caso, N sondas em vez de 1).
"""

import threading
import time
from collections.abc import Callable
from enum import StrEnum


class State(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        cooldown_s: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        if failure_threshold < 1 or cooldown_s <= 0:
            raise ValueError("failure_threshold >= 1 e cooldown_s > 0")
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> State:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> State:
        if self._opened_at is None:
            return State.CLOSED
        if self._clock() - self._opened_at >= self.cooldown_s:
            return State.HALF_OPEN
        return State.OPEN

    def allow(self) -> bool:
        """Pode chamar o serviço agora? No meio aberto, só uma sonda por vez."""
        with self._lock:
            state = self._state_unlocked()
            if state is State.CLOSED:
                return True
            if state is State.HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._probe_in_flight = False
            if self._opened_at is not None:
                # sonda falhou (ou falha atrasada de antes de abrir): reabre
                self._opened_at = self._clock()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()

    def release(self) -> None:
        """A chamada permitida terminou sem veredito (ex.: resposta descartada
        pela checagem de números): libera a sonda sem mudar o estado."""
        with self._lock:
            self._probe_in_flight = False

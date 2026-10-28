"""Circuit breaker: transições de estado, BVA no limiar e no tempo de espera, sonda única."""

import threading

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.breaker import CircuitBreaker, State


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(threshold=3, cooldown=60):
    clock = Clock()
    return CircuitBreaker(threshold, cooldown, clock=clock), clock


def test_closed_allows_and_success_resets_count():
    b, _ = make()
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is State.CLOSED and b.allow()


@pytest.mark.parametrize(
    ("failures", "state"), [(2, State.CLOSED), (3, State.OPEN), (4, State.OPEN)]
)
def test_opens_exactly_at_threshold(failures, state):
    b, _ = make(threshold=3)
    for _ in range(failures):
        b.record_failure()
    assert b.state is state


@pytest.mark.parametrize(
    ("elapsed", "state"), [(59.999, State.OPEN), (60, State.HALF_OPEN), (61, State.HALF_OPEN)]
)
def test_cooldown_boundary(elapsed, state):
    b, clock = make(threshold=1, cooldown=60)
    b.record_failure()
    clock.t += elapsed
    assert b.state is state
    assert b.allow() is (state is State.HALF_OPEN)


def test_half_open_lets_exactly_one_probe():
    b, clock = make(threshold=1, cooldown=10)
    b.record_failure()
    clock.t += 10
    assert b.allow() is True
    assert b.allow() is False  # segunda requisição não vira sonda


def test_probe_success_closes():
    b, clock = make(threshold=1, cooldown=10)
    b.record_failure()
    clock.t += 10
    assert b.allow()
    b.record_success()
    assert b.state is State.CLOSED and b.allow() and b.allow()


def test_probe_failure_reopens_for_full_cooldown():
    b, clock = make(threshold=3, cooldown=10)
    for _ in range(3):
        b.record_failure()
    clock.t += 10
    assert b.allow()
    b.record_failure()  # uma falha na sonda já reabre (não precisa de 3)
    assert b.state is State.OPEN
    clock.t += 9.9
    assert not b.allow()
    clock.t += 0.1
    assert b.allow()


def test_release_frees_probe_without_changing_state():
    b, clock = make(threshold=1, cooldown=10)
    b.record_failure()
    clock.t += 10
    assert b.allow()
    b.release()
    assert b.state is State.HALF_OPEN
    assert b.allow()  # outra sonda pode tentar


@pytest.mark.parametrize(("threshold", "cooldown"), [(0, 10), (1, 0), (-1, 5)])
def test_rejects_invalid_config(threshold, cooldown):
    with pytest.raises(ValueError):
        CircuitBreaker(threshold, cooldown)


@given(st.lists(st.booleans(), max_size=60), st.integers(1, 5))
def test_property_open_iff_last_n_were_failures(outcomes, threshold):
    """Sem passar tempo: o circuito está aberto se e somente se houve `threshold`
    falhas seguidas em algum momento desde o último sucesso."""
    b, _ = make(threshold=threshold, cooldown=60)
    run = 0
    opened = False
    for ok in outcomes:
        if not b.allow():
            assert opened
            continue
        if ok:
            b.record_success()
            run, opened = 0, False
        else:
            b.record_failure()
            run += 1
            opened = opened or run >= threshold
    assert (b.state is State.OPEN) is opened


def test_concurrent_half_open_single_probe():
    b, clock = make(threshold=1, cooldown=1)
    b.record_failure()
    clock.t += 1
    results = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        results.append(b.allow())

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1

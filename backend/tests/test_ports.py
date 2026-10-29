"""Cada adaptador de produção cumpre o contrato do seu port.

`runtime_checkable` só confere que os métodos existem; aqui também se compara a
assinatura (nomes, ordem e padrões dos parâmetros), para que um adaptador que
mude um parâmetro não continue "passando" sem o port saber.
"""

import inspect

import pytest

from app import ports
from app.auth import verify_google_id_token
from app.db import Database
from app.jobs import JobRunner
from app.llm import GeminiChat
from app.storage import Storage


def _params(fn) -> list[tuple[str, object, object]]:
    sig = inspect.signature(fn)
    return [(p.name, p.kind, p.default) for p in sig.parameters.values() if p.name not in ("self",)]


def _members(protocol) -> list[str]:
    return [
        n
        for n, v in vars(protocol).items()
        if callable(v) and not n.startswith("_") or n == "__call__"
    ]


@pytest.mark.parametrize(
    ("protocol", "adapter"),
    [
        (ports.Repository, Database),
        (ports.FileStore, Storage),
        (ports.JobQueue, JobRunner),
        (ports.ChatModel, GeminiChat),
    ],
)
def test_adapter_matches_port_signatures(protocol, adapter):
    assert _members(protocol), protocol  # o teste não pode passar por vazio
    for name in _members(protocol):
        assert hasattr(adapter, name), f"{adapter.__name__} sem {name}"
        assert _params(getattr(adapter, name)) == _params(getattr(protocol, name)), name


def test_google_verifier_matches_identity_port():
    assert isinstance(verify_google_id_token, ports.IdentityVerifier)
    assert _params(verify_google_id_token) == _params(ports.IdentityVerifier.__call__)


def test_fakes_used_in_tests_satisfy_ports(tmp_path):
    from tests.api.conftest import fake_verifier
    from tests.api.test_chat_api import FakeModel

    assert isinstance(fake_verifier, ports.IdentityVerifier)
    assert isinstance(FakeModel(), ports.ChatModel)
    assert isinstance(Database(tmp_path / "t.sqlite3"), ports.Repository)
    assert isinstance(Storage(tmp_path), ports.FileStore)

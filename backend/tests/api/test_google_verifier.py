"""Lógica do verificador real do Google, com a checagem criptográfica simulada.

verify_oauth2_token (google-auth) confere assinatura, audiência e expiração;
aqui garantimos o que fazemos com o resultado e com as falhas dele.
"""

import pytest

from app import auth
from app.auth import verify_google_id_token
from app.ports import InvalidIdentity

GOOD = {
    "iss": "https://accounts.google.com",
    "sub": "123",
    "email": "a@example.com",
    "email_verified": True,
    "name": "A",
}


def _patch(monkeypatch, result):
    calls = {}

    def fake(token, request, audience, clock_skew_in_seconds=0):
        calls["audience"] = audience
        calls["skew"] = clock_skew_in_seconds
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", fake)
    return calls


def test_valid_token(monkeypatch):
    calls = _patch(monkeypatch, GOOD)
    ident = verify_google_id_token("t", "my-client-id")
    assert (ident.sub, ident.email, ident.name) == ("123", "a@example.com", "A")
    assert calls["audience"] == "my-client-id"  # audiência sempre conferida
    assert calls["skew"] == 10  # tolera relógios levemente fora de sincronia


@pytest.mark.parametrize("iss", ["accounts.google.com", "https://accounts.google.com"])
def test_both_google_issuers_accepted(monkeypatch, iss):
    _patch(monkeypatch, {**GOOD, "iss": iss})
    assert verify_google_id_token("t", "c").sub == "123"


@pytest.mark.parametrize(
    ("claims", "msg"),
    [
        ({**GOOD, "iss": "https://evil.example.com"}, "emissor"),
        ({**GOOD, "email_verified": False}, "não verificado"),
        ({k: v for k, v in GOOD.items() if k != "email_verified"}, "não verificado"),
    ],
)
def test_rejected_claims(monkeypatch, claims, msg):
    _patch(monkeypatch, claims)
    with pytest.raises(InvalidIdentity, match=msg):
        verify_google_id_token("t", "c")


def test_library_failure_becomes_invalid_token(monkeypatch):
    _patch(monkeypatch, ValueError("Token expired"))
    with pytest.raises(InvalidIdentity):
        verify_google_id_token("t", "c")

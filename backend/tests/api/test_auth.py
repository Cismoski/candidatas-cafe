"""Autenticação: 401 sem sessão, JWT adulterado/expirado/revogado, login inválido."""

import time

import jwt
import pytest

from tests.api.conftest import login

PROTECTED = [
    ("get", "/me"),
    ("post", "/auth/logout"),
    ("get", "/analyses"),
    ("post", "/analyses"),
    ("get", "/analyses/00000000-0000-0000-0000-000000000000"),
    ("get", "/analyses/00000000-0000-0000-0000-000000000000/files/geojson"),
    ("delete", "/analyses/00000000-0000-0000-0000-000000000000"),
    ("get", "/analyses/00000000-0000-0000-0000-000000000000/chat"),
    ("post", "/analyses/00000000-0000-0000-0000-000000000000/chat"),
]


def test_health_is_public(client):
    # sem GEMINI_API_KEY nos testes: assistente em modo automático
    assert client.get("/health").json() == {"status": "ok", "assistente": "automatico"}


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_require_token(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_every_route_is_either_public_or_protected(client):
    """Guarda contra rota nova esquecida sem autenticação."""
    public = {
        "/health",
        "/auth/google",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
    routes = {r.path for r in client.app.routes}
    protected = {
        p.replace("{analysis_id}", "00000000-0000-0000-0000-000000000000").replace(
            "{name}", "geojson"
        )
        for p in routes - public
    }
    assert protected == {p for _, p in PROTECTED}


def test_login_with_invalid_google_token(client):
    r = client.post("/auth/google", json={"credential": "google-token-forjado"})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [{}, {"credential": ""}, {"credential": "x" * 5000}])
def test_login_payload_validation(client, body):
    assert client.post("/auth/google", json=body).status_code == 422


def test_login_returns_session_and_me(client, alice):
    me = client.get("/me", headers=alice).json()
    assert me["email"] == "alice@example.com"
    assert "google_sub" not in me


def test_login_is_idempotent_per_google_account(client):
    a = client.get("/me", headers=login(client, "google-token-alice")).json()
    b = client.get("/me", headers=login(client, "google-token-alice")).json()
    assert a["id"] == b["id"]


def _forge(settings, **changes):
    key = changes.pop("_key", settings.jwt_secret.get_secret_value())
    now = int(time.time())
    payload = {
        "sub": "x",
        "jti": "j",
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    payload.update(changes)
    return jwt.encode(payload, key, algorithm="HS256")


def test_tampered_and_invalid_tokens_rejected(client, settings, alice):
    me = client.get("/me", headers=alice).json()
    valid = alice["Authorization"].split()[1]
    header, payload, sig = valid.split(".")
    cases = {
        "assinatura trocada": f"{header}.{payload}.{sig[::-1]}",
        "segredo errado": _forge(settings, sub=me["id"], _key="y" * 48),
        "expirado": _forge(settings, sub=me["id"], exp=int(time.time()) - 1),
        "audiência errada": _forge(settings, sub=me["id"], aud="outro-app"),
        "emissor errado": _forge(settings, sub=me["id"], iss="outro"),
        "usuário inexistente": _forge(settings, sub="00000000-0000-0000-0000-000000000000"),
        "alg none": jwt.encode({"sub": me["id"], "jti": "a"}, None, algorithm="none"),
        "lixo": "abc.def.ghi",
    }
    for name, token in cases.items():
        r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, name


def test_missing_required_claim_rejected(client, settings, alice):
    me = client.get("/me", headers=alice).json()
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": me["id"],
            "exp": now + 60,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )  # sem jti/iat: não dá para revogar
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_non_bearer_scheme_rejected(client, alice):
    token = alice["Authorization"].split()[1]
    assert client.get("/me", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_logout_revokes_token(client, alice):
    assert client.post("/auth/logout", headers=alice).status_code == 204
    assert client.get("/me", headers=alice).status_code == 401
    # outra sessão do mesmo usuário continua válida
    other = login(client, "google-token-alice")
    assert client.get("/me", headers=other).status_code == 200


def test_cors_only_allows_configured_origin(client):
    ok = client.options(
        "/analyses",
        headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://app.example.com"
    bad = client.options(
        "/analyses",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"

"""Limites de uso: rajada por usuário (slowapi), cota diária (banco) e login por IP."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import fake_verifier, login, make_settings, upload


def test_upload_burst_limit_per_user(client, alice, bob, scene_bytes):
    codes = [upload(client, alice, scene_bytes).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    # o limite é por usuário: Bob não é afetado pela rajada de Alice
    assert upload(client, bob, scene_bytes).status_code == 202


def test_daily_quota_and_refund_on_rejected_upload(tmp_path, scene_bytes):
    s = make_settings(tmp_path, uploads_per_day=1)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:
        h = login(c, "google-token-alice")
        # upload rejeitado na validação devolve a cota
        assert upload(c, h, b"nao sou tiff").status_code == 422
        assert upload(c, h, scene_bytes).status_code == 202
        r = upload(c, h, scene_bytes)  # 3ª requisição: dentro da rajada (3/min), fora da cota
        assert r.status_code == 429 and "por dia" in r.json()["detail"]


def test_login_rate_limited_per_ip(client):
    codes = [
        client.post("/auth/google", json={"credential": "google-token-invalido"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    assert (
        "Muitas requisições"
        in client.post("/auth/google", json={"credential": "google-token-invalido"}).json()[
            "detail"
        ]
    )


def test_default_limit_applies_but_health_is_exempt(client, alice):
    assert all(client.get("/health").status_code == 200 for _ in range(130))
    codes = [client.get("/me", headers=alice).status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429


def test_rate_limit_key_uses_rightmost_forwarded_hop(tmp_path):
    """Com 1 proxy confiável, o IP é a última entrada do X-Forwarded-For.
    A primeira entrada é controlada pelo cliente e não pode trocar a chave."""
    s = make_settings(tmp_path, trusted_proxy_hops=1)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:

        def attempt(spoofed):
            return c.post(
                "/auth/google",
                json={"credential": "google-token-invalido"},
                headers={"X-Forwarded-For": f"{spoofed}, 203.0.113.7"},
            ).status_code

        codes = [attempt(f"10.0.0.{i}") for i in range(11)]
        assert codes[:10] == [401] * 10 and codes[10] == 429  # forjar o 1º IP não ajuda
        other = c.post(
            "/auth/google",
            json={"credential": "google-token-invalido"},
            headers={"X-Forwarded-For": "203.0.113.8"},
        )
        assert other.status_code == 401  # outro cliente real não é bloqueado

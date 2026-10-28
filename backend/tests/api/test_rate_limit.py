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


def test_health_is_not_rate_limited(client):
    assert all(client.get("/health").status_code == 200 for _ in range(130))

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ports import Identity, InvalidIdentity
from app.settings import Settings
from tests.conftest import COFFEE, make_scene, paint, write_stack

CLIENT_ID = "test-client.apps.googleusercontent.com"

# "Tokens" do Google falsos: o verificador real (assinatura RSA do Google) é
# substituído; o que se testa aqui é o que a API faz com o resultado.
USERS = {
    "google-token-alice": Identity(sub="google-sub-alice", email="alice@example.com", name="Alice"),
    "google-token-bob": Identity(sub="google-sub-bob", email="bob@example.com", name="Bob"),
}


def fake_verifier(token: str, client_id: str) -> Identity:
    assert client_id == CLIENT_ID
    if token not in USERS:
        raise InvalidIdentity("token inválido")
    return USERS[token]


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "google_client_id": CLIENT_ID,
        "jwt_secret": "x" * 48,
        "data_dir": tmp_path / "data",
        "cors_origins": "https://app.example.com",
        "job_isolation": False,
        "max_upload_mb": 5,
        "mapbiomas_url": "",  # sem rede nos testes; a comparação tem testes próprios
    }
    return Settings(_env_file=None, **{**base, **overrides})


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, google_verifier=fake_verifier)) as c:
        yield c


def login(client: TestClient, google_token: str) -> dict:
    r = client.post("/auth/google", json={"credential": google_token})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def alice(client):
    return login(client, "google-token-alice")


@pytest.fixture
def bob(client):
    return login(client, "google-token-bob")


@pytest.fixture
def scene_bytes(tmp_path) -> bytes:
    dn = make_scene(60, 60)
    paint(dn, slice(20, 30), slice(20, 30), **COFFEE)
    return write_stack(tmp_path / "upload.tif", dn).read_bytes()


def upload(client, headers, data: bytes, filename="cena.tif", **extra_files):
    """Envia e espera a fila de processamento esvaziar (o job roda em outra thread)."""
    files = {"primary": (filename, data, "image/tiff")}
    files.update(extra_files)
    r = client.post("/analyses", headers=headers, files=files)
    client.app.state.services.jobs.drain(timeout=60)
    return r

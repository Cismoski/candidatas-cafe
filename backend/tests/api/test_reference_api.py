"""Fiação da referência: JobRunner -> subprocesso -> pipeline -> summary e download."""

import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import fake_verifier, login, make_settings, upload
from tests.processing.test_reference import COFFEE, write_mb


def test_reference_url_reaches_the_pipeline_and_overlay_is_downloadable(tmp_path, scene_bytes):
    write_mb(tmp_path / "mb_2025.tif", np.full((20, 20), COFFEE, np.uint8))
    s = make_settings(tmp_path)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:
        # a Settings só aceita https; aqui o arquivo local entra direto no JobRunner
        c.app.state.services.jobs.reference_url = str(tmp_path / "mb_{year}.tif")
        alice = login(c, "google-token-alice")
        aid = upload(c, alice, scene_bytes).json()["id"]
        a = c.get(f"/analyses/{aid}", headers=alice).json()
        assert a["summary"]["reference"]["status"] == "ok"
        assert a["summary"]["map"]["reference_overlay"] is True
        r = c.get(f"/analyses/{aid}/files/overlay-reference", headers=alice)
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
        bob = login(c, "google-token-bob")
        assert c.get(f"/analyses/{aid}/files/overlay-reference", headers=bob).status_code == 404


def test_disabled_reference_has_no_overlay(tmp_path, scene_bytes):
    with TestClient(create_app(make_settings(tmp_path), google_verifier=fake_verifier)) as c:
        alice = login(c, "google-token-alice")
        aid = upload(c, alice, scene_bytes).json()["id"]
        assert c.get(f"/analyses/{aid}", headers=alice).json()["summary"]["reference"] is None
        assert c.get(f"/analyses/{aid}/files/overlay-reference", headers=alice).status_code == 404

"""Upload, processamento, downloads, isolamento entre usuários e retenção."""

import io
import threading
from datetime import timedelta

import numpy as np
import pytest
from PIL import Image

from app import jobs
from app.db import Database, iso, now
from app.main import sweep
from app.ports import QuotaExceeded
from tests.api.conftest import upload
from tests.conftest import make_scene, write_stack


def _done(client, headers, data):
    r = upload(client, headers, data)
    assert r.status_code == 202, r.text
    a = client.get(f"/analyses/{r.json()['id']}", headers=headers).json()
    assert a["status"] == "done", a
    return a


# --- fluxo feliz ---------------------------------------------------------------
def test_upload_process_and_download(client, alice, scene_bytes):
    a = _done(client, alice, scene_bytes)
    r = a["summary"]["results"]
    assert r["candidate_polygons"] == 1 and r["candidate_area_ha"] == pytest.approx(1.0)
    assert a["title"] == "cena.tif"
    assert a["expires_at"] > a["created_at"]

    gj = client.get(f"/analyses/{a['id']}/files/geojson", headers=alice)
    assert gj.status_code == 200
    assert gj.headers["content-type"].startswith("application/geo+json")
    assert gj.headers["content-disposition"].startswith("attachment")
    assert len(gj.json()["features"]) == 1

    png = client.get(f"/analyses/{a['id']}/files/png", headers=alice)
    assert Image.open(io.BytesIO(png.content)).format == "PNG"
    overlay = client.get(f"/analyses/{a['id']}/files/overlay-rgb", headers=alice)
    assert "attachment" not in overlay.headers.get("content-disposition", "")  # exibida no mapa
    tif = client.get(f"/analyses/{a['id']}/files/geotiff", headers=alice)
    assert tif.content[:4] in (b"II*\x00", b"MM\x00*")

    listed = client.get("/analyses", headers=alice).json()
    assert [x["id"] for x in listed] == [a["id"]] and "summary" not in listed[0]


def test_user_filename_never_becomes_a_path(client, alice, scene_bytes, settings):
    r = upload(client, alice, scene_bytes, filename="../../../../etc/passwd.tif")
    assert r.status_code == 202
    files = {p.name for p in settings.data_dir.rglob("*") if p.is_file()}
    assert "passwd.tif" not in files and "primaria.tif" in files
    escaped = [p for p in settings.data_dir.parent.rglob("passwd*")]
    assert escaped == []


def test_title_is_normalized_and_limited(client, alice, scene_bytes):
    r = client.post(
        "/analyses",
        headers=alice,
        files={"primary": ("a.tif", scene_bytes, "image/tiff")},
        data={"title": "  Fazenda   \n Boa Vista  "},
    )
    assert r.json()["title"] == "Fazenda Boa Vista"
    r = client.post(
        "/analyses",
        headers=alice,
        files={"primary": ("a.tif", scene_bytes, "image/tiff")},
        data={"title": "x" * 81},
    )
    assert r.status_code == 422


# --- isolamento entre usuários --------------------------------------------------
def test_user_cannot_access_another_users_analysis(client, alice, bob, scene_bytes, settings):
    a = _done(client, alice, scene_bytes)
    base = f"/analyses/{a['id']}"
    # Bob recebe 404 (não 403): não revela que a análise existe
    assert client.get(base, headers=bob).status_code == 404
    for name in ("geojson", "png", "geotiff", "overlay-rgb", "overlay-classes"):
        assert client.get(f"{base}/files/{name}", headers=bob).status_code == 404
    assert client.delete(base, headers=bob).status_code == 404
    assert client.get("/analyses", headers=bob).json() == []
    # e nada mudou para Alice
    assert client.get(base, headers=alice).json()["status"] == "done"
    assert client.get(f"{base}/files/geojson", headers=alice).status_code == 200


def test_files_are_stored_per_owner(client, alice, bob, scene_bytes, settings):
    a = _done(client, alice, scene_bytes)
    b = _done(client, bob, scene_bytes)
    root = settings.data_dir / "users"
    owners = [p.name for p in root.iterdir()]
    assert len(owners) == 2
    a_owner = next(o for o in owners if (root / o / a["id"]).exists())
    assert not (root / a_owner / b["id"]).exists()


@pytest.mark.parametrize(
    "path",
    [
        "/analyses/..%2F..%2Fetc",
        "/analyses/not-a-uuid",
        "/analyses/00000000-0000-0000-0000-000000000000",
    ],
)
def test_bad_or_unknown_ids_are_404(client, alice, path):
    assert client.get(path, headers=alice).status_code == 404


@pytest.mark.parametrize("name", ["summary", "..%2Fprimaria.tif", "inputs", "candidatas.geojson"])
def test_only_allowlisted_files_downloadable(client, alice, scene_bytes, name):
    a = _done(client, alice, scene_bytes)
    assert client.get(f"/analyses/{a['id']}/files/{name}", headers=alice).status_code == 404


# --- validação do upload -----------------------------------------------------------
def _tif(tmp_path, name, dn, **kw):
    return write_stack(tmp_path / name, dn, **kw).read_bytes()


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda t: b"", "vazio"),
        (lambda t: b"%PDF-1.4 nao sou tiff", "não é um GeoTIFF"),
        (lambda t: _png_bytes(), "não é um GeoTIFF"),
        (lambda t: b"II*\x00" + b"\x00" * 100, "não foi possível ler"),
        (lambda t: _tif(t, "b3.tif", make_scene(8, 8)[:3]), "de 4 a 13 bandas"),
        (lambda t: _tif(t, "b14.tif", np.ones((14, 8, 8), np.uint16)), "de 4 a 13 bandas"),
        (lambda t: _tif(t, "f.tif", make_scene(8, 8).astype(np.float32)), "uint16"),
        (
            lambda t: _tif(
                t, "g.tif", make_scene(8, 8), crs="EPSG:4326", res=0.0001, origin=(-46.7, -21.3)
            ),
            "não é UTM",
        ),
        (lambda t: _tif(t, "nocrs.tif", make_scene(8, 8), crs=None), "CRS"),
        (lambda t: _tif(t, "big.tif", make_scene(8, 1501)), "excede o máximo"),
        (lambda t: _tif(t, "px.tif", make_scene(8, 8), res=100.0), "pixel de 100 m"),
    ],
)
def test_invalid_uploads_rejected_with_clear_message(
    client, alice, tmp_path, settings, make, message
):
    r = upload(client, alice, make(tmp_path))
    assert r.status_code == 422
    assert message in r.json()["detail"]
    # nada fica no disco nem no banco, e a cota é devolvida
    assert not any(p.is_file() for p in (settings.data_dir / "users").rglob("*"))
    assert client.get("/analyses", headers=alice).json() == []


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


def test_invalid_scl_rejected(client, alice, scene_bytes, tmp_path):
    bad_scl = _tif(tmp_path, "scl.tif", make_scene(8, 8))  # 4 bandas
    r = upload(client, alice, scene_bytes, scl=("scl.tif", bad_scl, "image/tiff"))
    assert r.status_code == 422 and "SCL" in r.json()["detail"]


def test_missing_primary_file(client, alice):
    assert client.post("/analyses", headers=alice).status_code == 422


def test_body_over_limit_is_413(client, alice):
    big = b"II*\x00" + b"\x00" * (5 * 1024 * 1024 + 10)
    r = upload(client, alice, big)
    assert r.status_code == 413
    assert "grande demais" in r.json()["detail"]


def test_content_length_over_limit_rejected_before_reading(client, alice):
    r = client.post(
        "/analyses",
        headers={
            **alice,
            "Content-Length": str(50 * 1024 * 1024),
            "Content-Type": "multipart/form-data; boundary=x",
        },
        content=b"--x--",
    )
    assert r.status_code == 413


# --- processamento com falha ---------------------------------------------------------
def test_scene_error_becomes_failed_with_message(client, alice, scene_bytes, tmp_path):
    far_scl = write_stack(
        tmp_path / "far.tif",
        np.full((1, 10, 10), 4, np.uint16),
        origin=(400000.0, 7600000.0),
        res=20.0,
    ).read_bytes()
    r = upload(client, alice, scene_bytes, scl=("scl.tif", far_scl, "image/tiff"))
    a = client.get(f"/analyses/{r.json()['id']}", headers=alice).json()
    assert a["status"] == "failed" and "SCL cobre só" in a["error"]
    assert client.get(f"/analyses/{a['id']}/files/geojson", headers=alice).status_code == 409


def test_unexpected_error_is_generic(client, alice, scene_bytes, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("detalhe interno /srv/segredo")

    monkeypatch.setattr(jobs, "_child", boom)
    r = upload(client, alice, scene_bytes)
    a = client.get(f"/analyses/{r.json()['id']}", headers=alice).json()
    assert a["status"] == "failed" and a["error"] == jobs.GENERIC_ERROR


# --- delete, concorrência e reinício ---------------------------------------------------
def test_delete_removes_record_and_files(client, alice, scene_bytes, settings):
    a = _done(client, alice, scene_bytes)
    assert client.delete(f"/analyses/{a['id']}", headers=alice).status_code == 204
    assert client.get(f"/analyses/{a['id']}", headers=alice).status_code == 404
    assert not list((settings.data_dir / "users").rglob(a["id"]))
    # idempotente do ponto de vista do cliente
    assert client.delete(f"/analyses/{a['id']}", headers=alice).status_code == 404


def test_job_discards_result_if_analysis_deleted_meanwhile(
    client, alice, scene_bytes, settings, monkeypatch
):
    app = client.app
    real = jobs.run_inline

    def run_then_delete(args, tmp):
        result = real(args, tmp)
        owner, aid = tmp.parent.parent.name, tmp.parent.name
        # usuário apagou DEPOIS do processamento e ANTES do rename
        app.state.services.db.delete_analysis(aid, owner)
        app.state.services.storage.remove_analysis(owner, aid)
        return result

    monkeypatch.setattr(jobs, "run_inline", run_then_delete)
    r = upload(client, alice, scene_bytes)
    assert client.get(f"/analyses/{r.json()['id']}", headers=alice).status_code == 404
    assert not list((settings.data_dir / "users").rglob(r.json()["id"]))


def test_interrupted_jobs_marked_failed_on_startup(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    u = db.upsert_user("s", "e@x.com", None)
    db.create_analysis("a1", u["id"], "t", False, False)
    db.set_status("a1", "processing")
    assert db.fail_interrupted() == 1
    a = db.get_analysis("a1", u["id"])
    assert a["status"] == "failed" and "reinício" in a["error"]


def test_quota_is_atomic_under_concurrency(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    u = db.upsert_user("s", "e@x.com", None)
    ok, denied = [], []

    def worker():
        try:
            db.consume_quota(u["id"], "upload", 5, timedelta(days=1))
            ok.append(1)
        except QuotaExceeded:
            denied.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 5 and len(denied) == 15


# --- retenção ------------------------------------------------------------------
def test_retention_sweep_deletes_old_analyses_and_orphans(client, alice, scene_bytes, settings):
    a = _done(client, alice, scene_bytes)
    b = _done(client, alice, scene_bytes)
    db, storage = client.app.state.services.db, client.app.state.services.storage
    old = iso(now() - timedelta(hours=settings.retention_hours + 1))
    with db.connect() as c:
        c.execute("UPDATE analyses SET created_at = ? WHERE id = ?", (old, a["id"]))
    orphan = (
        storage.root
        / "11111111-1111-1111-1111-111111111111"
        / "22222222-2222-2222-2222-222222222222"
    )
    orphan.mkdir(parents=True)
    old_mtime = (now() - timedelta(hours=2)).timestamp()
    import os

    os.utime(orphan, (old_mtime, old_mtime))
    assert sweep(db, storage, settings) == 1
    ids = [x["id"] for x in client.get("/analyses", headers=alice).json()]
    assert ids == [b["id"]]
    assert not list(storage.root.rglob(a["id"])) and not orphan.parent.exists()


# --- subprocesso real (uma vez: é o caminho de produção) -----------------------------
def test_isolated_subprocess_path(tmp_path, scene_bytes):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.api.conftest import fake_verifier, login, make_settings

    s = make_settings(tmp_path, job_isolation=True)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:
        h = login(c, "google-token-alice")
        r = upload(c, h, scene_bytes)
        a = c.get(f"/analyses/{r.json()['id']}", headers=h).json()
    assert a["status"] == "done" and a["summary"]["results"]["candidate_polygons"] == 1


def test_subprocess_timeout_and_crash(tmp_path):
    args = ("/nao/existe.tif", str(tmp_path / "o"), {}, None, None)
    # cfg vazio falha na validação dentro do filho -> código != 0
    assert jobs.run_isolated(args, tmp_path / "o", timeout_s=60) == jobs.GENERIC_ERROR
    # timeout ínfimo: o filho é terminado
    assert jobs.run_isolated(args, tmp_path / "o", timeout_s=0) == jobs.TIMEOUT_ERROR


# --- itens da revisão da fase 2 -------------------------------------------------------
def test_oversized_body_on_any_route_is_413(client):
    """Sem token: corpo grande em /auth/google era lido inteiro para a memória."""
    r = client.post(
        "/auth/google",
        content=b"{" + b" " * (65 * 1024) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_chunked_body_over_limit_is_413(client, alice):
    """Sem Content-Length: o contador de bytes do middleware corta o corpo."""

    def gen():
        for _ in range(6):
            yield b"\x00" * (1024 * 1024)

    r = client.post(
        "/analyses",
        headers={**alice, "Content-Type": "multipart/form-data; boundary=x"},
        content=gen(),
    )
    assert r.status_code == 413


def test_anonymous_multipart_gets_401_before_parsing(client, monkeypatch):
    from starlette.requests import Request

    def boom(*a, **k):
        raise AssertionError("o corpo não deveria ser lido")

    monkeypatch.setattr(Request, "form", boom)
    r = client.post("/analyses", files={"primary": ("a.tif", b"II*\x00" + b"0" * 1000)})
    assert r.status_code == 401
    r = client.post(
        "/analyses",
        headers={"Authorization": "Bearer lixo"},
        files={"primary": ("a.tif", b"II*\x00")},
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "files",
    [
        {"outro": ("a.tif", b"II*\x00")},
        [("primary", ("a.tif", b"II*\x00")), ("primary", ("b.tif", b"II*\x00"))],
        [
            ("primary", ("a.tif", b"II*\x00")),
            ("scl", ("s.tif", b"II*\x00")),
            ("secondary", ("c.tif", b"II*\x00")),
            ("extra", ("d.tif", b"II*\x00")),
        ],
    ],
)
def test_unexpected_form_fields_rejected(client, alice, files):
    assert client.post("/analyses", headers=alice, files=files).status_code in (400, 422)


def test_band_bomb_rejected_by_header(client, alice, tmp_path):
    """TIFF pequeno que declara muitas bandas (GBs descomprimidos) é rejeitado sem ler pixels."""
    import rasterio
    from rasterio.transform import from_origin

    p = tmp_path / "bomb.tif"
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        dtype="uint16",
        count=200,
        height=1500,
        width=1500,
        crs="EPSG:32723",
        transform=from_origin(323200, 7642980, 10, 10),
        compress="deflate",
        sparse_ok=True,
        tiled=True,
    ):
        pass  # nenhum pixel escrito: arquivo minúsculo
    assert p.stat().st_size < 2 * 1024 * 1024
    r = upload(client, alice, p.read_bytes())
    assert r.status_code == 422 and "bandas" in r.json()["detail"]


def test_queue_full_returns_503(tmp_path, scene_bytes):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.api.conftest import fake_verifier, login, make_settings

    s = make_settings(tmp_path, max_queued_jobs=1)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:
        h = login(c, "google-token-alice")
        c.app.state.services.db.create_analysis(  # um job "preso" na fila
            "33333333-3333-3333-3333-333333333333",
            c.get("/me", headers=h).json()["id"],
            "x",
            False,
            False,
        )
        r = upload(c, h, scene_bytes)
        assert r.status_code == 503
        assert c.get("/health").status_code == 200


def test_idempotency_key_returns_same_analysis(client, alice, scene_bytes):
    h = {**alice, "Idempotency-Key": "upload-0001-abc"}
    files = {"primary": ("a.tif", scene_bytes, "image/tiff")}
    first = client.post("/analyses", headers=h, files=files)
    client.app.state.services.jobs.drain(60)
    second = client.post("/analyses", headers=h, files=files)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/analyses", headers=alice).json()) == 1
    bad = client.post("/analyses", headers={**alice, "Idempotency-Key": "x"}, files=files)
    assert bad.status_code == 422


def test_idempotency_key_is_scoped_per_user(client, alice, bob, scene_bytes):
    files = {"primary": ("a.tif", scene_bytes, "image/tiff")}
    a = client.post("/analyses", headers={**alice, "Idempotency-Key": "same-key-123"}, files=files)
    b = client.post("/analyses", headers={**bob, "Idempotency-Key": "same-key-123"}, files=files)
    assert a.status_code == b.status_code == 202 and a.json()["id"] != b.json()["id"]
    client.app.state.services.jobs.drain(60)


def test_rejected_uploads_have_their_own_quota(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.api.conftest import fake_verifier, login, make_settings

    s = make_settings(tmp_path, uploads_per_day=1)
    with TestClient(create_app(s, google_verifier=fake_verifier)) as c:
        h = login(c, "google-token-alice")
        uid = c.get("/me", headers=h).json()["id"]
        for _ in range(3):  # 3 * uploads_per_day rejeições permitidas
            c.app.state.services.db.consume_quota(uid, "upload_rejected", 3, timedelta(days=1))
        r = upload(c, h, b"nao sou tiff")
        assert r.status_code == 429 and "inválidos" in r.json()["detail"]


def test_validation_errors_do_not_echo_input(client):
    r = client.post("/auth/google", json={"credential": "segredo"})
    assert r.status_code == 422 and "segredo" not in r.text


def test_orphan_sweep_spares_recent_upload_dirs(client, settings):
    storage = client.app.state.services.storage
    d = (
        storage.root
        / "44444444-4444-4444-4444-444444444444"
        / "55555555-5555-5555-5555-555555555555"
    )
    d.mkdir(parents=True)  # upload em andamento: arquivos antes da linha no banco
    assert storage.remove_orphans(set()) == 0 and d.exists()


def test_downloads_are_not_cached(client, alice, scene_bytes):
    a = _done(client, alice, scene_bytes)
    r = client.get(f"/analyses/{a['id']}/files/png", headers=alice)
    assert "no-store" in r.headers["cache-control"]


def test_inactive_users_without_analyses_are_purged(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    keep = db.upsert_user("k", "k@x.com", None)
    gone = db.upsert_user("g", "g@x.com", None)
    old = iso(now() - timedelta(days=40))
    with db.connect() as c:
        c.execute("UPDATE users SET last_login_at = ?", (old,))
    db.create_analysis("a1", keep["id"], "t", False, False)
    db.purge_expired(now() - timedelta(days=365), now() - timedelta(days=30))
    assert db.get_user(keep["id"]) is not None and db.get_user(gone["id"]) is None

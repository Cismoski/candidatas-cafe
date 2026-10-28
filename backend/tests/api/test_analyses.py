"""Upload, processamento, downloads, isolamento entre usuários e retenção."""

import io
import threading
from datetime import timedelta

import numpy as np
import pytest
from PIL import Image

from app import jobs
from app.db import Database, QuotaExceeded, iso, now
from app.main import sweep
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
        (lambda t: _tif(t, "b3.tif", make_scene(8, 8)[:3]), "4 bandas"),
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
    real = jobs._run

    def delete_then_run(args, tmp, isolate, timeout_s):
        owner = tmp.parent.parent.name
        aid = tmp.parent.name
        app.state.db.delete_analysis(aid, owner)  # usuário apagou durante o processamento
        return real(args, tmp, isolate, timeout_s)

    monkeypatch.setattr(jobs, "_run", delete_then_run)
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
    db, storage = client.app.state.db, client.app.state.storage
    old = iso(now() - timedelta(hours=settings.retention_hours + 1))
    with db.connect() as c:
        c.execute("UPDATE analyses SET created_at = ? WHERE id = ?", (old, a["id"]))
    orphan = (
        storage.root
        / "11111111-1111-1111-1111-111111111111"
        / "22222222-2222-2222-2222-222222222222"
    )
    orphan.mkdir(parents=True)
    assert sweep(db, storage, settings.retention_hours) == 1
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


def test_subprocess_timeout_is_enforced(tmp_path):
    args = ("/nao/existe.tif", str(tmp_path / "o"), {}, None, None)
    # cfg vazio falha na validação dentro do filho -> código != 0
    assert jobs._run(args, tmp_path / "o", isolate=True, timeout_s=60) == jobs.GENERIC_ERROR
    # timeout ínfimo: o filho é terminado
    assert jobs._run(args, tmp_path / "o", isolate=True, timeout_s=0) == jobs.TIMEOUT_ERROR

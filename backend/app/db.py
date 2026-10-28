"""Persistência em SQLite (stdlib).

Por que SQLite: uma instância única no plano gratuito, volume de dados mínimo e
retenção curta. WAL permite leituras concorrentes com a thread de processamento;
cada operação abre a própria conexão, então não há conexão compartilhada entre
threads. Toda consulta de análise filtra por owner_id: isolamento entre usuários
é garantido na camada de dados, não só na rota.
"""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    google_sub  TEXT NOT NULL UNIQUE,
    email       TEXT NOT NULL,
    name        TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('pending','processing','done','failed')),
    error         TEXT,
    title         TEXT NOT NULL,
    has_scl       INTEGER NOT NULL,
    has_secondary INTEGER NOT NULL,
    summary_json  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_owner_created ON analyses(owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_analyses_created ON analyses(created_at);
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti         TEXT PRIMARY KEY,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_events (
    user_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_usage_user_kind_time ON usage_events(user_id, kind, created_at);
"""


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class QuotaExceeded(Exception):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE: pega o lock de escrita já no início (check-then-insert atômico)."""
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    # --- usuários -----------------------------------------------------------
    def upsert_user(self, google_sub: str, email: str, name: str | None) -> dict:
        with self.transaction() as c:
            row = c.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
            if row:
                c.execute(
                    "UPDATE users SET email = ?, name = ? WHERE id = ?", (email, name, row["id"])
                )
                return {**dict(row), "email": email, "name": name}
            user = {
                "id": str(uuid.uuid4()),
                "google_sub": google_sub,
                "email": email,
                "name": name,
                "created_at": iso(now()),
            }
            c.execute(
                "INSERT INTO users (id, google_sub, email, name, created_at) "
                "VALUES (:id, :google_sub, :email, :name, :created_at)",
                user,
            )
            return user

    def get_user(self, user_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    # --- tokens revogados ------------------------------------------------------
    def revoke_token(self, jti: str, expires_at: datetime) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
                (jti, iso(expires_at)),
            )

    def is_revoked(self, jti: str) -> bool:
        with self.connect() as c:
            return (
                c.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
                is not None
            )

    # --- cotas -------------------------------------------------------------------
    def consume_quota(self, user_id: str, kind: str, limit: int, window: timedelta) -> int:
        """Registra um uso se ainda houver cota na janela; devolve quantos restam.

        Contagem e inserção na mesma transação IMMEDIATE: duas requisições
        simultâneas não conseguem ambas passar do limite.
        """
        since = iso(now() - window)
        with self.transaction() as c:
            used = c.execute(
                "SELECT COUNT(*) FROM usage_events WHERE user_id = ? AND kind = ? AND created_at > ?",
                (user_id, kind, since),
            ).fetchone()[0]
            if used >= limit:
                raise QuotaExceeded(kind)
            c.execute(
                "INSERT INTO usage_events (user_id, kind, created_at) VALUES (?, ?, ?)",
                (user_id, kind, iso(now())),
            )
            return limit - used - 1

    def release_quota(self, user_id: str, kind: str) -> None:
        """Devolve o uso mais recente (ex.: upload rejeitado na validação)."""
        with self.connect() as c:
            c.execute(
                "DELETE FROM usage_events WHERE rowid = (SELECT rowid FROM usage_events "
                "WHERE user_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1)",
                (user_id, kind),
            )

    # --- análises ----------------------------------------------------------------
    def create_analysis(
        self, analysis_id: str, owner_id: str, title: str, has_scl: bool, has_secondary: bool
    ) -> None:
        ts = iso(now())
        with self.connect() as c:
            c.execute(
                "INSERT INTO analyses (id, owner_id, status, title, has_scl, has_secondary, "
                "created_at, updated_at) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)",
                (analysis_id, owner_id, title, int(has_scl), int(has_secondary), ts, ts),
            )

    def set_status(
        self,
        analysis_id: str,
        status: str,
        *,
        error: str | None = None,
        summary: dict | None = None,
    ) -> bool:
        """Atualiza o status; devolve False se a análise foi apagada no meio do caminho."""
        with self.connect() as c:
            cur = c.execute(
                "UPDATE analyses SET status = ?, error = ?, summary_json = ?, updated_at = ? WHERE id = ?",
                (
                    status,
                    error,
                    json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                    iso(now()),
                    analysis_id,
                ),
            )
            return cur.rowcount == 1

    @staticmethod
    def _row_to_analysis(row: sqlite3.Row, with_summary: bool) -> dict:
        d = dict(row)
        raw = d.pop("summary_json")
        d["has_scl"] = bool(d["has_scl"])
        d["has_secondary"] = bool(d["has_secondary"])
        if with_summary:
            d["summary"] = json.loads(raw) if raw else None
        return d

    def get_analysis(self, analysis_id: str, owner_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM analyses WHERE id = ? AND owner_id = ?", (analysis_id, owner_id)
            ).fetchone()
            return self._row_to_analysis(row, True) if row else None

    def list_analyses(self, owner_id: str, limit: int = 50) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                "SELECT * FROM analyses WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
            return [self._row_to_analysis(r, False) for r in rows]

    def delete_analysis(self, analysis_id: str, owner_id: str) -> bool:
        with self.connect() as c:
            cur = c.execute(
                "DELETE FROM analyses WHERE id = ? AND owner_id = ?", (analysis_id, owner_id)
            )
            return cur.rowcount == 1

    def fail_interrupted(self) -> int:
        """Na partida: análises que estavam em andamento morreram com o processo."""
        with self.connect() as c:
            cur = c.execute(
                "UPDATE analyses SET status = 'failed', error = ?, updated_at = ? "
                "WHERE status IN ('pending', 'processing')",
                (
                    "Processamento interrompido por reinício do servidor. Envie novamente.",
                    iso(now()),
                ),
            )
            return cur.rowcount

    # --- retenção ------------------------------------------------------------------
    def purge_expired(self, older_than: datetime) -> list[tuple[str, str]]:
        """Apaga análises antigas e devolve (owner_id, id) para remover os arquivos."""
        cutoff = iso(older_than)
        with self.transaction() as c:
            rows = c.execute(
                "SELECT owner_id, id FROM analyses WHERE created_at < ?", (cutoff,)
            ).fetchall()
            c.execute("DELETE FROM analyses WHERE created_at < ?", (cutoff,))
            c.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (iso(now()),))
            c.execute(
                "DELETE FROM usage_events WHERE created_at < ?", (iso(now() - timedelta(days=2)),)
            )
            return [(r["owner_id"], r["id"]) for r in rows]

    def analysis_ids(self) -> set[str]:
        with self.connect() as c:
            return {r[0] for r in c.execute("SELECT id FROM analyses")}

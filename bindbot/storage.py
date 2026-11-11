"""Собственная база бота (SQLite): список серверов, привязки, неудачные попытки."""
import asyncio
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .crypto import Crypto


@dataclass
class Server:
    id: int
    name: str
    host: str
    port: int
    db_user: str
    db_pass: str
    db_name: str
    table: str
    enabled: bool


@dataclass
class Binding:
    id: int
    tg_id: int
    server_id: int
    account_id: int
    nickname: str
    hash_variant: str


class Storage:
    def __init__(self, path: str, crypto: Crypto):
        self._crypto = crypto
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS servers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                db_user TEXT NOT NULL,
                db_pass TEXT NOT NULL,
                db_name TEXT NOT NULL,
                tbl TEXT NOT NULL DEFAULT 'accounts',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bindings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                server_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                nickname TEXT NOT NULL,
                hash_variant TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                UNIQUE(server_id, account_id)
            );
            CREATE INDEX IF NOT EXISTS idx_bindings_tg ON bindings(tg_id);
            CREATE TABLE IF NOT EXISTS failures(
                tg_id INTEGER NOT NULL,
                ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_failures ON failures(tg_id, ts);
            """
        )
        self._db.commit()

    # ---- низкоуровневое ----
    def _sync(self, sql, params=(), fetch="none"):
        with self._lock:
            cur = self._db.execute(sql, params)
            rows = cur.fetchall() if fetch == "all" else cur.fetchone() if fetch == "one" else None
            self._db.commit()
            return rows if fetch != "none" else cur.lastrowid

    async def _q(self, sql, params=(), fetch="none"):
        return await asyncio.to_thread(self._sync, sql, params, fetch)

    def _server(self, r) -> Server:
        return Server(r["id"], r["name"], r["host"], r["port"], r["db_user"],
                      self._crypto.decrypt(r["db_pass"]), r["db_name"], r["tbl"], bool(r["enabled"]))

    # ---- серверы ----
    async def add_server(self, name, host, port, db_user, db_pass, db_name, table="accounts") -> int:
        return await self._q(
            "INSERT INTO servers(name,host,port,db_user,db_pass,db_name,tbl,enabled,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
            (name, host, port, db_user, self._crypto.encrypt(db_pass), db_name, table, int(time.time())))

    async def upsert_server(self, name, host, port, db_user, db_pass, db_name, table, enabled=True) -> tuple:
        """Создаёт сервер или обновляет существующий с тем же названием. Возвращает (id, создан_ли)."""
        r = await self._q("SELECT id FROM servers WHERE name=?", (name,), "one")
        enc = self._crypto.encrypt(db_pass)
        if r:
            await self._q(
                "UPDATE servers SET host=?,port=?,db_user=?,db_pass=?,db_name=?,tbl=?,enabled=? WHERE id=?",
                (host, port, db_user, enc, db_name, table, int(enabled), r["id"]))
            return r["id"], False
        sid = await self._q(
            "INSERT INTO servers(name,host,port,db_user,db_pass,db_name,tbl,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (name, host, port, db_user, enc, db_name, table, int(enabled), int(time.time())))
        return sid, True

    async def list_servers(self, only_enabled=False) -> list:
        sql = "SELECT * FROM servers" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id"
        return [self._server(r) for r in await self._q(sql, fetch="all")]

    async def get_server(self, server_id: int) -> Optional[Server]:
        r = await self._q("SELECT * FROM servers WHERE id=?", (server_id,), "one")
        return self._server(r) if r else None

    async def toggle_server(self, server_id: int) -> None:
        await self._q("UPDATE servers SET enabled = 1 - enabled WHERE id=?", (server_id,))

    async def delete_server(self, server_id: int) -> None:
        await self._q("DELETE FROM bindings WHERE server_id=?", (server_id,))
        await self._q("DELETE FROM servers WHERE id=?", (server_id,))

    async def bindings_per_server(self) -> dict:
        rows = await self._q("SELECT server_id, COUNT(*) c FROM bindings GROUP BY server_id", fetch="all")
        return {r["server_id"]: r["c"] for r in rows}

    # ---- привязки ----
    def _binding(self, r) -> Binding:
        return Binding(r["id"], r["tg_id"], r["server_id"], r["account_id"], r["nickname"], r["hash_variant"])

    async def add_binding(self, tg_id, server_id, account_id, nickname, hash_variant) -> int:
        return await self._q(
            "INSERT INTO bindings(tg_id,server_id,account_id,nickname,hash_variant,created_at) VALUES(?,?,?,?,?,?)",
            (tg_id, server_id, account_id, nickname, hash_variant, int(time.time())))

    async def get_binding(self, binding_id: int) -> Optional[Binding]:
        r = await self._q("SELECT * FROM bindings WHERE id=?", (binding_id,), "one")
        return self._binding(r) if r else None

    async def find_binding(self, server_id: int, account_id: int) -> Optional[Binding]:
        r = await self._q("SELECT * FROM bindings WHERE server_id=? AND account_id=?", (server_id, account_id), "one")
        return self._binding(r) if r else None

    async def list_bindings(self, tg_id: int) -> list:
        rows = await self._q("SELECT * FROM bindings WHERE tg_id=? ORDER BY id", (tg_id,), "all")
        return [self._binding(r) for r in rows]

    async def set_variant(self, binding_id: int, variant: str) -> None:
        await self._q("UPDATE bindings SET hash_variant=? WHERE id=?", (variant, binding_id))

    async def delete_binding(self, binding_id: int) -> None:
        await self._q("DELETE FROM bindings WHERE id=?", (binding_id,))

    # ---- защита от подбора ----
    async def note_failure(self, tg_id: int) -> None:
        await self._q("INSERT INTO failures(tg_id,ts) VALUES(?,?)", (tg_id, int(time.time())))

    async def failures_recent(self, tg_id: int, window_sec: int) -> int:
        r = await self._q("SELECT COUNT(*) c FROM failures WHERE tg_id=? AND ts>?",
                          (tg_id, int(time.time()) - window_sec), "one")
        return r["c"]

    async def clear_failures(self, tg_id: int) -> None:
        await self._q("DELETE FROM failures WHERE tg_id=?", (tg_id,))

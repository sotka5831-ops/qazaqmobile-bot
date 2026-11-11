"""Подключение к MySQL-базам игровых серверов (у каждого сервера свой пул)."""
import re
from typing import Optional

import aiomysql

from .storage import Server

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Недопустимое имя таблицы/колонки: {name!r}")
    return f"`{name}`"


class GameDB:
    def __init__(self):
        self._pools = {}

    async def _pool(self, s: Server):
        key = (s.id, s.host, s.port, s.db_user, s.db_pass, s.db_name)
        pool = self._pools.get(s.id)
        if pool and pool[0] == key:
            return pool[1]
        if pool:
            pool[1].close()
            await pool[1].wait_closed()
        p = await aiomysql.create_pool(
            host=s.host, port=s.port, user=s.db_user, password=s.db_pass, db=s.db_name,
            minsize=0, maxsize=3, autocommit=True, connect_timeout=6, charset="utf8mb4")
        self._pools[s.id] = (key, p)
        return p

    async def drop(self, server_id: int):
        pool = self._pools.pop(server_id, None)
        if pool:
            pool[1].close()
            await pool[1].wait_closed()

    async def close_all(self):
        for sid in list(self._pools):
            await self.drop(sid)

    async def test(self, s: Server) -> str:
        """Пустая строка - всё хорошо, иначе текст ошибки."""
        try:
            pool = await self._pool(s)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"SELECT COUNT(*) FROM {_ident(s.table)}")
                    await cur.fetchone()
            return ""
        except Exception as e:  # noqa: BLE001
            await self.drop(s.id)
            return f"{type(e).__name__}: {e}"

    async def _fetch_one(self, s: Server, sql: str, args=()):
        pool = await self._pool(s)
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchone()

    async def _exec(self, s: Server, sql: str, args=()) -> int:
        pool = await self._pool(s)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)
                return cur.rowcount

    # ---- аккаунты ----
    _COLS = "id, name, password, salt, setting_pin_code, AdminPass, admin"

    async def find_by_name(self, s: Server, nickname: str) -> Optional[dict]:
        return await self._fetch_one(
            s, f"SELECT {self._COLS} FROM {_ident(s.table)} WHERE name=%s LIMIT 1", (nickname,))

    async def find_by_id(self, s: Server, account_id: int) -> Optional[dict]:
        return await self._fetch_one(
            s, f"SELECT {self._COLS} FROM {_ident(s.table)} WHERE id=%s LIMIT 1", (account_id,))

    async def set_password(self, s: Server, account_id: int, pw_hash: str, salt: str) -> bool:
        n = await self._exec(
            s, f"UPDATE {_ident(s.table)} SET password=%s, salt=%s WHERE id=%s LIMIT 1", (pw_hash, salt, account_id))
        return n == 1

    async def set_pin(self, s: Server, account_id: int, pin: str) -> bool:
        n = await self._exec(
            s, f"UPDATE {_ident(s.table)} SET setting_pin_code=%s WHERE id=%s LIMIT 1", (pin, account_id))
        return n == 1

    async def set_admin_pass(self, s: Server, account_id: int, value: int) -> bool:
        n = await self._exec(
            s, f"UPDATE {_ident(s.table)} SET AdminPass=%s WHERE id=%s AND admin>0 LIMIT 1", (value, account_id))
        return n == 1

    async def delete_account(self, s: Server, account_id: int, cascade: list) -> bool:
        pool = await self._pool(s)
        async with pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    for table, col in cascade:
                        try:
                            await cur.execute(f"DELETE FROM {_ident(table)} WHERE {_ident(col)}=%s", (account_id,))
                        except aiomysql.ProgrammingError as e:
                            if e.args and e.args[0] == 1146:  # таблицы нет - пропускаем
                                continue
                            raise
                    await cur.execute(f"DELETE FROM {_ident(s.table)} WHERE id=%s LIMIT 1", (account_id,))
                    ok = cur.rowcount == 1
                if ok:
                    await conn.commit()
                else:
                    await conn.rollback()
                return ok
            except Exception:
                await conn.rollback()
                raise

from .config import DATABASE_URL, DB_PATH

_schema_sqlite = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS removed (
    chat_id BIGINT PRIMARY KEY,
    removed_at TEXT DEFAULT ''
);
"""

_schema_pg = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS removed (
    chat_id BIGINT PRIMARY KEY,
    removed_at TEXT DEFAULT ''
);
"""


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Sqlite:
    def __init__(self):
        import aiosqlite

        self._aiosqlite = aiosqlite
        self.path = DB_PATH

    async def _connect(self):
        db = await self._aiosqlite.connect(self.path)
        db.row_factory = self._aiosqlite.Row
        return db

    async def init(self):
        async with self._aiosqlite.connect(self.path) as db:
            await db.executescript(_schema_sqlite)
            await db.commit()

    async def execute(self, sql, params=()):
        db = await self._connect()
        try:
            await db.execute(sql, params)
            await db.commit()
        finally:
            await db.close()

    async def fetchall(self, sql, params=()):
        db = await self._connect()
        try:
            cur = await db.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

    async def fetchone(self, sql, params=()):
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None


class _Pg:
    def __init__(self):
        self._pool = None

    async def pool(self):
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
        return self._pool

    def _sql(self, sql: str) -> str:
        out, i = [], 0
        for ch in sql:
            if ch == "?":
                i += 1
                out.append(f"${i}")
            else:
                out.append(ch)
        return "".join(out)

    async def init(self):
        pool = await self.pool()
        async with pool.acquire() as con:
            await con.execute(_schema_pg)

    async def execute(self, sql, params=()):
        pool = await self.pool()
        async with pool.acquire() as con:
            await con.execute(self._sql(sql), *params)

    async def fetchall(self, sql, params=()):
        pool = await self.pool()
        async with pool.acquire() as con:
            rows = await con.fetch(self._sql(sql), *params)
        return [dict(r) for r in rows]

    async def fetchone(self, sql, params=()):
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None


class Database:
    def __init__(self):
        self._adapter = None

    @property
    def adapter(self):
        if self._adapter is None:
            self._adapter = _Pg() if DATABASE_URL else _Sqlite()
        return self._adapter

    @property
    def is_pg(self) -> bool:
        return DATABASE_URL != ""

    def init(self):
        return self.adapter.init()

    async def get(self, key: str) -> str:
        row = await self.adapter.fetchone("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else ""

    async def set(self, key: str, value: str) -> None:
        await self.adapter.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def add_removed(self, chat_id: int) -> None:
        await self.adapter.execute(
            "INSERT INTO removed(chat_id, removed_at) VALUES(?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET removed_at=excluded.removed_at",
            (chat_id, _now()),
        )

    async def removed_ids(self) -> set[int]:
        rows = await self.adapter.fetchall("SELECT chat_id FROM removed")
        return {int(r["chat_id"]) for r in rows}

    async def close(self) -> None:
        if isinstance(self._adapter, _Pg) and self._adapter._pool is not None:
            await self._adapter._pool.close()


db = Database()
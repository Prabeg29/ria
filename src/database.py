from contextlib import asynccontextmanager

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from .settings import settings


class DatabaseSessionManager:
    def __init__(self, dsn: str | None = ""):
        if not dsn:
            raise Exception("Database url not found")
        
        self._pool = AsyncConnectionPool(dsn, open=False)

    async def open_pool(self):
        await self._pool.open()

    async def close_pool(self):
        await self._pool.close()

    @asynccontextmanager
    async def connection(self):
        async with self._pool.connection() as aconn:
            yield aconn


db = DatabaseSessionManager(settings.db_url)


async def init_db():
    INIT_DB_QUERIES = [
        sql.SQL(
            """
        CREATE TABLE IF NOT EXISTS ria.resumes(
            id UUID NOT NULL,
            filename VARCHAR(255) NOT NULL,
            raw_text TEXT,
            parsed_data JSON,
            s3_url VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW () NOT NULL,
            deleted_at TIMESTAMP,
            CONSTRAINT pk_resumes PRIMARY KEY (id)
        );
        """
        ),
        sql.SQL(
            """
        CREATE INDEX IF NOT EXISTS ix_ria_resumes_id ON ria.resumes (id);
        """
        ),
    ]

    async with db.connection() as conn:
        for query in INIT_DB_QUERIES:
            await conn.execute(query=query)


from contextlib import asynccontextmanager

from psycopg import AsyncConnection, sql

from .settings import settings


@asynccontextmanager
async def db_conn():
    async with await AsyncConnection.connect(settings.db_url) as aconn:
        yield aconn


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
        sql.SQL(
            """
                CREATE TABLE IF NOT EXISTS ria.scraped_jobs(
                    id UUID NOT NULL,
                    url TEXT NOT NULL,
                    url_hash CHAR(64) UNIQUE NOT NULL,
                    scraped_data JSONB NOT NULL,
                    scraped_at TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true
                );
            """
        )
        sql.SQL(
            """
                CREATE INDEX IF NOT EXISTS ix_ria_scraped_jobs_id ON ria.scraped_jobs (id);
            """
        ),
    ]

    async with db_conn() as conn:
        for query in INIT_DB_QUERIES:
            await conn.execute(query=query)

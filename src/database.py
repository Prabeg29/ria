from contextlib import asynccontextmanager
from pathlib import Path

from psycopg import AsyncConnection

from .settings import settings


@asynccontextmanager
async def db_conn():
    async with await AsyncConnection.connect(settings.db_url) as aconn:
        yield aconn


async def init_db():
    sql_file = Path(__file__).parent.parent / "database" / "init.sql"
    if not sql_file.exists():
        raise FileNotFoundError(f"SQL file not found at {sql_file}")

    with open(sql_file, "r") as f:
        queries = f.read()

    async with db_conn() as conn:
        await conn.execute(queries)

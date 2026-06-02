import asyncio
import secrets
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from src.database import db_conn
from src.main import app
from src.utils import hash_url


@pytest.fixture(scope="session")
def api_key() -> Generator[str, None, None]:
    key = secrets.token_urlsafe(32)
    tenant_id = uuid.uuid4()
    api_key_id = uuid.uuid4()

    async def _seed() -> None:
        async with db_conn() as conn:
            await conn.execute(
                """
                    INSERT INTO ria.tenants (id, email)
                    VALUES (%s, %s);
                """,
                (str(tenant_id), f"test-{tenant_id}@example.com"),
            )
            await conn.execute(
                """
                    INSERT INTO ria.api_keys (id, tenant_id, key_hash)
                    VALUES (%s, %s, %s);
                """,
                (str(api_key_id), str(tenant_id), hash_url(key)),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.tenants WHERE id = %s;",
                (str(tenant_id),),
            )

    asyncio.run(_seed())

    yield key

    asyncio.run(_teardown())


@pytest.fixture(scope="module")
def client(api_key: str) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        c.headers["X-API-KEY"] = api_key
        yield c

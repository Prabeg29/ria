import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Generator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from src.database import db_conn, init_db
from src.main import app
from src.utils import hash_url, rate_limiter


@pytest.fixture(scope="session", autouse=True)
def setup_database() -> None:
    asyncio.run(init_db())


@pytest.fixture(scope="session")
def api_key(setup_database: None) -> Generator[str, None, None]:
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


class SeededScrapedJob(NamedTuple):
    id: str
    url: str
    url_hash: str


@pytest.fixture
def seed_scraped_job() -> Generator[Callable[[str, str], SeededScrapedJob], None, None]:
    created_ids: list[str] = []

    def _create(url: str, status: str = "queued") -> SeededScrapedJob:
        job_id = str(uuid.uuid4())
        url_hash = hashlib.sha256(url.encode()).hexdigest()

        async def _seed() -> None:
            async with db_conn() as conn:
                await conn.execute(
                    """
                        INSERT INTO ria.scraped_jobs (
                            id, normalized_url, url_hash, status, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, NOW(), NOW());
                    """,
                    (job_id, url, url_hash, status),
                )

        asyncio.run(_seed())
        created_ids.append(job_id)
        return SeededScrapedJob(job_id, url, url_hash)

    yield _create

    async def _teardown() -> None:
        async with db_conn() as conn:
            for job_id in created_ids:
                await conn.execute(
                    "DELETE FROM ria.scraped_jobs WHERE id = %s;",
                    (job_id,),
                )

    asyncio.run(_teardown())


@pytest.fixture(autouse=True)
def disable_rate_limit(request: pytest.FixtureRequest) -> Generator[None, Any, None]:
    if request.node.get_closest_marker("rate_limit"):
        yield
    else:
        rate_limiter.enabled = False
        yield
        rate_limiter.enabled = True


@pytest.fixture(scope="module")
def client(api_key: str) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        c.headers["X-API-KEY"] = api_key
        yield c

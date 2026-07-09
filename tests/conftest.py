import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Generator

pytest_plugins = ["tests.fixtures.pdf"]
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from src.database import db_conn, init_db
from src.main import app
from src.settings import settings
from src.utils import hash_url, rate_limiter


class SeededResume(NamedTuple):
    id: str
    content_hash: str
    s3_key: str


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
def seed_scraped_job() -> Generator[Callable[..., SeededScrapedJob], None, None]:
    created_ids: list[str] = []

    def _create(
        url: str,
        status: str = "queued",
        scraped_data: dict[str, Any] | None = None,
        is_archived: bool = False,
    ) -> SeededScrapedJob:
        job_id = str(uuid.uuid4())
        url_hash = hashlib.sha256(url.encode()).hexdigest()

        async def _seed() -> None:
            async with db_conn() as conn:
                await conn.execute(
                    """
                        INSERT INTO ria.scraped_jobs (
                            id, normalized_url, url_hash, status, scraped_data,
                            is_archived, last_scraped_at, created_at, updated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s = 'scraped' THEN NOW() END, NOW(), NOW()
                        );
                    """,
                    (
                        job_id,
                        url,
                        url_hash,
                        status,
                        Json(scraped_data) if scraped_data is not None else None,
                        is_archived,
                        status,
                    ),
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


@pytest.fixture
def seed_resume() -> Generator[Callable[[str, str | None], SeededResume], None, None]:
    created_ids: list[str] = []

    def _create(processing_status: str, raw_text: str | None = None) -> SeededResume:
        content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        resume_id = str(uuid.uuid4())
        s3_key = f"resumes/{resume_id}-resume.pdf"

        async def _seed() -> None:
            async with db_conn() as conn:
                await conn.execute(
                    """
                        INSERT INTO ria.resumes (
                            id,
                            content_hash,
                            filename,
                            s3_key,
                            processing_status,
                            raw_text,
                            last_upload_presigned_url_generated_at,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW());
                    """,
                    (resume_id, content_hash, "resume.pdf", s3_key, processing_status, raw_text),
                )

        asyncio.run(_seed())
        created_ids.append(resume_id)
        return SeededResume(resume_id, content_hash, s3_key)

    yield _create

    async def _teardown() -> None:
        async with db_conn() as conn:
            for resume_id in created_ids:
                await conn.execute(
                    "DELETE FROM ria.resumes WHERE id = %s;",
                    (resume_id,),
                )

    asyncio.run(_teardown())


@pytest.fixture
def flush_rate_limit() -> Generator[None, None, None]:
    """Delete the limiter's Redis counters after a rate-limited test so the
    consumed window does not bleed into other tests."""
    yield

    redis = settings.redis_conn
    keys = list(redis.scan_iter("LIMITER*"))
    if keys:
        redis.delete(*keys)


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

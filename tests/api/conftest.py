import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Generator
from typing import NamedTuple

import pytest

from src.database import db_conn
from src.deps import get_scraper_registry
from src.main import app
from tests.fixtures.stubs import StubScraperRegistry


class SeededResume(NamedTuple):
    id: str
    content_hash: str
    s3_key: str


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


@pytest.fixture(scope="module")
def stub_scraper_registry() -> Generator[None, None, None]:
    app.dependency_overrides[get_scraper_registry] = lambda: StubScraperRegistry()
    yield
    app.dependency_overrides.pop(get_scraper_registry, None)

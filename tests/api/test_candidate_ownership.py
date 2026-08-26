import asyncio
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable, Generator
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from redis import Redis

from src.database import db_conn
from src.main import app
from src.settings import settings
from src.utils import hash_url
from tests.conftest import SeededResume, SeededScrapedJob


pytestmark = pytest.mark.usefixtures("stub_scraper_registry")


class CandidateAccess(NamedTuple):
    id: uuid.UUID
    api_key: str


class CandidateSessions(NamedTuple):
    client: TestClient
    first: CandidateAccess
    second: CandidateAccess


@pytest.fixture
def candidate_sessions() -> Generator[CandidateSessions, None, None]:
    candidates = [
        CandidateAccess(id=uuid.uuid4(), api_key=secrets.token_urlsafe(32))
        for _ in range(2)
    ]

    async def _seed() -> None:
        async with db_conn() as conn:
            for candidate in candidates:
                await conn.execute(
                    """
                        INSERT INTO ria.tenants (id, email)
                        VALUES (%s, %s);
                    """,
                    (candidate.id, f"candidate-{candidate.id}@example.com"),
                )
                await conn.execute(
                    """
                        INSERT INTO ria.api_keys (id, tenant_id, key_hash)
                        VALUES (%s, %s, %s);
                    """,
                    (uuid.uuid4(), candidate.id, hash_url(candidate.api_key)),
                )

    async def _teardown() -> None:
        candidate_ids = [candidate.id for candidate in candidates]
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE candidate_id = ANY(%s);",
                (candidate_ids,),
            )
            await conn.execute(
                "DELETE FROM ria.tenants WHERE id = ANY(%s);",
                (candidate_ids,),
            )

    with TestClient(app) as client:
        asyncio.run(_seed())
        try:
            yield CandidateSessions(client, candidates[0], candidates[1])
        finally:
            asyncio.run(_teardown())


@pytest.fixture
def seed_candidate_resume(
    candidate_sessions: CandidateSessions,
) -> Generator[Callable[..., SeededResume], None, None]:
    created_ids: list[uuid.UUID] = []

    def _create(
        candidate: CandidateAccess,
        processing_status: str,
        raw_text: str | None = None,
    ) -> SeededResume:
        resume_id = uuid.uuid4()
        content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        s3_key = f"resumes/{resume_id}-resume.pdf"

        async def _seed() -> None:
            async with db_conn() as conn:
                await conn.execute(
                    """
                        INSERT INTO ria.resumes (
                            id,
                            candidate_id,
                            content_hash,
                            filename,
                            s3_key,
                            processing_status,
                            raw_text,
                            last_upload_presigned_url_generated_at,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW());
                    """,
                    (
                        resume_id,
                        candidate.id,
                        content_hash,
                        "resume.pdf",
                        s3_key,
                        processing_status,
                        raw_text,
                    ),
                )

        asyncio.run(_seed())
        created_ids.append(resume_id)
        return SeededResume(str(resume_id), content_hash, s3_key, str(candidate.id))

    yield _create

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = ANY(%s);",
                (created_ids,),
            )

    asyncio.run(_teardown())


def candidate_headers(candidate: CandidateAccess) -> dict[str, str]:
    return {"X-API-KEY": candidate.api_key}


def test_missing_api_key_remains_unauthorized(
    candidate_sessions: CandidateSessions,
) -> None:
    response = candidate_sessions.client.post(
        "/resumes/upload/complete",
        json={"resume_id": str(uuid.uuid4())},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_invalid_api_key_remains_forbidden(
    candidate_sessions: CandidateSessions,
) -> None:
    response = candidate_sessions.client.post(
        "/resumes/upload/complete",
        headers={"X-API-KEY": "invalid"},
        json={"resume_id": str(uuid.uuid4())},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_identical_resume_content_is_independent_between_candidates(
    candidate_sessions: CandidateSessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3_client = MagicMock()
    s3_client.generate_presigned_post.return_value = {
        "url": "https://uploads.example.test",
        "fields": {},
    }
    monkeypatch.setattr("src.api.s3_client", s3_client)
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    payload = {
        "filename": "resume.pdf",
        "size": 1024,
        "content_type": "application/pdf",
    }

    first_response = candidate_sessions.client.post(
        "/resumes/upload/init",
        headers={
            **candidate_headers(candidate_sessions.first),
            "X-Content-Hash": content_hash,
        },
        json=payload,
    )
    second_response = candidate_sessions.client.post(
        "/resumes/upload/init",
        headers={
            **candidate_headers(candidate_sessions.second),
            "X-Content-Hash": content_hash,
        },
        json=payload,
    )
    duplicate_response = candidate_sessions.client.post(
        "/resumes/upload/init",
        headers={
            **candidate_headers(candidate_sessions.first),
            "X-Content-Hash": content_hash,
        },
        json=payload,
    )

    assert first_response.status_code == status.HTTP_200_OK
    assert second_response.status_code == status.HTTP_200_OK
    assert first_response.json()["id"] != second_response.json()["id"]
    assert duplicate_response.status_code == status.HTTP_400_BAD_REQUEST


def test_foreign_resume_is_not_revealed_or_dispatched_for_completion(
    candidate_sessions: CandidateSessions,
    seed_candidate_resume: Callable[..., SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume = seed_candidate_resume(candidate_sessions.first, "s3_uploaded")
    extract_resume_text = MagicMock()
    monkeypatch.setattr("src.api.extract_resume_text", extract_resume_text)

    response = candidate_sessions.client.post(
        "/resumes/upload/complete",
        headers=candidate_headers(candidate_sessions.second),
        json={"resume_id": resume.id},
    )
    missing_response = candidate_sessions.client.post(
        "/resumes/upload/complete",
        headers=candidate_headers(candidate_sessions.second),
        json={"resume_id": str(uuid.uuid4())},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == missing_response.json()
    extract_resume_text.delay.assert_not_called()


def test_foreign_resume_is_not_revealed_or_dispatched_for_analysis(
    candidate_sessions: CandidateSessions,
    seed_candidate_resume: Callable[..., SeededResume],
    seed_scraped_job: Callable[[str, str], SeededScrapedJob],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume = seed_candidate_resume(
        candidate_sessions.first,
        "raw_extracted",
        raw_text="Experienced software engineer",
    )
    scrape_job_details = MagicMock()
    ingress_llm = MagicMock()
    job_url = "https://www.seek.com.au/job/ownership-test"
    seed_scraped_job(job_url, "scraped")
    monkeypatch.setattr("src.api.scrape_job_details", scrape_job_details)
    monkeypatch.setattr("src.api.ingress_llm", ingress_llm)

    response = candidate_sessions.client.post(
        f"/resumes/{resume.id}/analyses",
        headers=candidate_headers(candidate_sessions.second),
        json={"job_url": job_url},
    )
    missing_response = candidate_sessions.client.post(
        f"/resumes/{uuid.uuid4()}/analyses",
        headers=candidate_headers(candidate_sessions.second),
        json={"job_url": job_url},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == missing_response.json()
    scrape_job_details.delay.assert_not_called()
    ingress_llm.delay.assert_not_called()


def test_owned_resume_completion_dispatches_with_candidate_context(
    candidate_sessions: CandidateSessions,
    seed_candidate_resume: Callable[..., SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume = seed_candidate_resume(candidate_sessions.first, "s3_uploaded")
    extract_resume_text = MagicMock()
    monkeypatch.setattr("src.api.extract_resume_text", extract_resume_text)

    response = candidate_sessions.client.post(
        "/resumes/upload/complete",
        headers=candidate_headers(candidate_sessions.first),
        json={"resume_id": resume.id},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    extract_resume_text.delay.assert_called_once_with(
        candidate_sessions.first.id,
        uuid.UUID(resume.id),
    )


def test_foreign_analysis_stream_is_not_revealed(
    candidate_sessions: CandidateSessions,
) -> None:
    job_id = str(uuid.uuid4())
    redis_client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
    )
    stream_key = f"analysis:stream:{job_id}"
    owner_key = f"analysis:owner:{job_id}"
    redis_client.set(owner_key, str(candidate_sessions.first.id))
    redis_client.xadd(stream_key, {"type": "done", "payload": json.dumps({})})

    try:
        response = candidate_sessions.client.get(
            f"/analysis/{job_id}/stream",
            headers=candidate_headers(candidate_sessions.second),
        )
    finally:
        redis_client.delete(stream_key, owner_key)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Analysis not found"}


def test_client_request_id_cannot_collide_analysis_ownership(
    candidate_sessions: CandidateSessions,
    seed_candidate_resume: Callable[..., SeededResume],
    seed_scraped_job: Callable[[str, str], SeededScrapedJob],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_resume = seed_candidate_resume(
        candidate_sessions.first, "raw_extracted", raw_text="First candidate"
    )
    second_resume = seed_candidate_resume(
        candidate_sessions.second, "raw_extracted", raw_text="Second candidate"
    )
    job_url = "https://www.seek.com.au/job/request-id-collision"
    seed_scraped_job(job_url, "scraped")
    monkeypatch.setattr("src.api.scrape_job_details", MagicMock())
    monkeypatch.setattr("src.api.ingress_llm", MagicMock())
    request_id = str(uuid.uuid4())

    first_response = candidate_sessions.client.post(
        f"/resumes/{first_resume.id}/analyses",
        headers={
            **candidate_headers(candidate_sessions.first),
            "X-REQUEST-ID": request_id,
        },
        json={"job_url": job_url},
    )
    second_response = candidate_sessions.client.post(
        f"/resumes/{second_resume.id}/analyses",
        headers={
            **candidate_headers(candidate_sessions.second),
            "X-REQUEST-ID": request_id,
        },
        json={"job_url": job_url},
    )
    first_job_id = first_response.json()["job_id"]
    second_job_id = second_response.json()["job_id"]

    try:
        assert first_job_id != second_job_id
        foreign_response = candidate_sessions.client.get(
            f"/analysis/{first_job_id}/stream",
            headers=candidate_headers(candidate_sessions.second),
        )
        assert foreign_response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        ).delete(
            f"analysis:owner:{first_job_id}",
            f"analysis:owner:{second_job_id}",
        )

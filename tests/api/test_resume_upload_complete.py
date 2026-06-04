import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Generator
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import status
from fastapi.testclient import TestClient

from src.database import db_conn
from src.settings import settings


class SeededResume(NamedTuple):
    id: str
    content_hash: str
    s3_key: str


@pytest.fixture
def seed_resume() -> Generator[Callable[[str], SeededResume], None, None]:
    """Insert a resume with the given processing status, returning its
    identifiers. Any seeded resume is deleted when the test finishes."""
    created_ids: list[str] = []

    def _create(processing_status: str) -> SeededResume:
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
                            last_upload_presigned_url_generated_at,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), NOW());
                    """,
                    (resume_id, content_hash, "resume.pdf", s3_key, processing_status),
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


def test_trigger_is_rejected_for_non_existing_id(client: TestClient) -> None:
    non_existing_id = str(uuid.uuid4())

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": non_existing_id
        }
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_trigger_is_rejected_for_processing_status_failed(
    client: TestClient,
    seed_resume: Callable[[str], SeededResume],
) -> None:
    resume = seed_resume("failed")

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": resume.id
        },
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_trigger_is_rejected_for_processing_status_llm_parsed(
    client: TestClient,
    seed_resume: Callable[[str], SeededResume],
) -> None:
    resume = seed_resume("llm_parsed")

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": resume.id
        },
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_s3_object_is_checked_for_processing_status_pending(
    client: TestClient,
    seed_resume: Callable[[str], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'pending' resume must trigger an S3 HEAD check to confirm the uploaded
    object exists before the resume is dispatched for further processing."""
    resume = seed_resume("pending")

    mock_s3_client = MagicMock()
    mock_extract_resume_text = MagicMock()
    monkeypatch.setattr("src.api.s3_client", mock_s3_client)
    monkeypatch.setattr("src.api.extract_resume_text", mock_extract_resume_text)

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": resume.id
        },
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    mock_s3_client.head_object.assert_called_once_with(
        Bucket=settings.aws_bucket,
        Key=resume.s3_key,
    )
    mock_extract_resume_text.delay.assert_called_once_with(uuid.UUID(resume.id))


def test_pending_resume_rejected_when_file_not_uploaded_to_s3(
    client: TestClient,
    seed_resume: Callable[[str], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'pending' resume whose object is missing from S3 must be rejected with
    422 and must not be dispatched for further processing."""
    resume = seed_resume("pending")

    # Simulate a missing S3 object: head_object raises a 404 ClientError.
    mock_s3_client = MagicMock()
    mock_s3_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}},
        "HeadObject",
    )
    mock_extract_resume_text = MagicMock()
    monkeypatch.setattr("src.api.s3_client", mock_s3_client)
    monkeypatch.setattr("src.api.extract_resume_text", mock_extract_resume_text)

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": resume.id
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    mock_s3_client.head_object.assert_called_once_with(
        Bucket=settings.aws_bucket,
        Key=resume.s3_key,
    )
    mock_extract_resume_text.delay.assert_not_called()

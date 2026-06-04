import asyncio
import hashlib
import secrets
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.database import db_conn
from src.settings import settings

def test_trigger_is_rejected_for_non_existing_id(client: TestClient) -> None:
    non_existing_id = str(uuid.uuid4())

    response = client.post(
        "/resumes/upload/complete",
        json={
            "resume_id": non_existing_id
        }
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_trigger_is_rejected_for_processing_status_failed(client: TestClient) -> None:
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    resume_id = str(uuid.uuid4())

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
                    VALUES (%s, %s, %s, %s, 'failed', NOW(), NOW(), NOW());
                """,
                (
                    resume_id,
                    content_hash,
                    "resume.pdf",
                    f"resumes/{resume_id}-resume.pdf",
                ),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = %s;",
                (resume_id,),
            )

    asyncio.run(_seed())

    try:
        response = client.post(
            "/resumes/upload/complete",
            json={
                "resume_id": resume_id
            },
        )
    finally:
        asyncio.run(_teardown())

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_trigger_is_rejected_for_processing_status_llm_parsed(client: TestClient) -> None:
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    resume_id = str(uuid.uuid4())

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
                    VALUES (%s, %s, %s, %s, 'llm_parsed', NOW(), NOW(), NOW());
                """,
                (
                    resume_id,
                    content_hash,
                    "resume.pdf",
                    f"resumes/{resume_id}-resume.pdf",
                ),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = %s;",
                (resume_id,),
            )

    asyncio.run(_seed())

    try:
        response = client.post(
            "/resumes/upload/complete",
            json={
                "resume_id": resume_id
            },
        )
    finally:
        asyncio.run(_teardown())

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_s3_object_is_checked_for_processing_status_pending(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'pending' resume must trigger an S3 HEAD check to confirm the uploaded
    object exists before the resume is dispatched for further processing."""
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
                    VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW(), NOW());
                """,
                (
                    resume_id,
                    content_hash,
                    "resume.pdf",
                    s3_key,
                ),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = %s;",
                (resume_id,),
            )

    mock_s3_client = MagicMock()
    mock_extract_resume_text = MagicMock()
    monkeypatch.setattr("src.api.s3_client", mock_s3_client)
    monkeypatch.setattr("src.api.extract_resume_text", mock_extract_resume_text)

    asyncio.run(_seed())

    try:
        response = client.post(
            "/resumes/upload/complete",
            json={
                "resume_id": resume_id
            },
        )
    finally:
        asyncio.run(_teardown())

    assert response.status_code == status.HTTP_202_ACCEPTED
    mock_s3_client.head_object.assert_called_once_with(
        Bucket=settings.aws_bucket,
        Key=s3_key,
    )
    mock_extract_resume_text.delay.assert_called_once_with(uuid.UUID(resume_id))

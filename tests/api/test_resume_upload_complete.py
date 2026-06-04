import asyncio
import hashlib
import secrets
import uuid

from fastapi import status
from fastapi.testclient import TestClient

from src.database import db_conn

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


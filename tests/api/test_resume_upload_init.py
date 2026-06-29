import asyncio
import hashlib
import secrets
import uuid

from fastapi import status
from fastapi.testclient import TestClient

from src.database import db_conn


def test_content_hash_exists_in_header(client: TestClient) -> None:
    response = client.post("/resumes/upload/init")

    assert response.status_code == status.HTTP_406_NOT_ACCEPTABLE


def test_upload_rejected_for_invalid_content_type(client: TestClient) -> None:
    """An unsupported content type must be rejected with 422 before any
    processing happens."""
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    response = client.post(
        "/resumes/upload/init",
        headers={"X-Content-Hash": content_hash},
        json={
            "filename": "resume.txt",
            "size": 1024,
            "content_type": "text/plain",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_upload_rejected_for_invalid_file_size(client: TestClient) -> None:
    """A file size outside the allowed 50 KB - 1 MB range must be rejected with
    422 before any processing happens."""
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    response = client.post(
        "/resumes/upload/init",
        headers={"X-Content-Hash": content_hash},
        json={
            "filename": "resume.pdf",
            "size": 10,
            "content_type": "application/pdf",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_reupload_rejected_when_presigned_url_recently_generated(
    client: TestClient,
) -> None:
    """A 'pending' resume whose presigned URL was generated less than 3 minutes
    ago must reject a re-upload with 400 to prevent duplicate uploads."""
    # Arrange: seed a pending resume whose presigned URL was generated just now.
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    resume_id = uuid.uuid4()

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
                    str(resume_id),
                    content_hash,
                    "resume.pdf",
                    f"resumes/{resume_id}-resume.pdf",
                ),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = %s;",
                (str(resume_id),),
            )

    asyncio.run(_seed())

    try:
        # Act: request a new upload for the same content hash.
        response = client.post(
            "/resumes/upload/init",
            headers={"X-Content-Hash": content_hash},
            json={
                "filename": "resume.pdf",
                "size": 1024,
                "content_type": "application/pdf",
            },
        )
    finally:
        asyncio.run(_teardown())

    # Assert: the duplicate upload is rejected.
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        response.json()["detail"]
        == "File has been previously uploaded, skipping processing"
    )


def test_presigned_url_is_generated_new_content_hash(client: TestClient) -> None:
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    response = client.post(
        "/resumes/upload/init",
        headers={"X-Content-Hash": content_hash},
        json={
            "filename": "resume.pdf",
            "size": 1024,
            "content_type": "application/pdf",
        },
    )

    assert response.status_code == status.HTTP_200_OK


def test_presigned_url_is_generated_for_old_content_hash_after_3_mins(client: TestClient) -> None:
    content_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    resume_id = uuid.uuid4()

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
                    VALUES (%s, %s, %s, %s, 'pending', NOW() - INTERVAL '4 minutes', NOW(), NOW());
                """,
                (
                    str(resume_id),
                    content_hash,
                    "resume.pdf",
                    f"resumes/{resume_id}-resume.pdf",
                ),
            )

    async def _teardown() -> None:
        async with db_conn() as conn:
            await conn.execute(
                "DELETE FROM ria.resumes WHERE id = %s;",
                (str(resume_id),),
            )

    asyncio.run(_seed())

    try:
        response = client.post(
            "/resumes/upload/init",
            headers={"X-Content-Hash": content_hash},
            json={
                "filename": "resume.pdf",
                "size": 1024,
                "content_type": "application/pdf",
            },
        )
    finally:
        asyncio.run(_teardown())

    assert response.status_code == status.HTTP_200_OK

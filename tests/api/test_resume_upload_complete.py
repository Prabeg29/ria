import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import status
from fastapi.testclient import TestClient

from src.settings import settings
from tests.conftest import SeededResume


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


def test_s3_object_is_skipped_for_processing_status_s3_uploaded(
    client: TestClient,
    seed_resume: Callable[[str], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 's3_uploaded' resume must not trigger an S3 HEAD check to confirm the uploaded
    object exists before the resume is dispatched for further processing."""
    resume = seed_resume("s3_uploaded")

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
    mock_s3_client.head_object.assert_not_called()
    mock_extract_resume_text.delay.assert_called_once_with(
        uuid.UUID(resume.candidate_id), uuid.UUID(resume.id)
    )


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
    mock_extract_resume_text.delay.assert_called_once_with(
        uuid.UUID(resume.candidate_id), uuid.UUID(resume.id)
    )


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


@pytest.mark.rate_limit
def test_upload_complete_returns_429_beyond_5_requests_per_minute(
    client: TestClient, flush_rate_limit: None
) -> None:
    """The 6th request within the fixed window must be rejected with 429; the
    first 5 must pass through the limiter (as 404s for unknown resume IDs,
    which keeps the requests free of S3 and queue side effects)."""
    # Act
    responses = [
        client.post(
            "/resumes/upload/complete",
            json={"resume_id": str(uuid.uuid4())},
        )
        for _ in range(6)
    ]

    # Assert
    assert all(
        response.status_code == status.HTTP_404_NOT_FOUND
        for response in responses[:5]
    )
    assert responses[5].status_code == status.HTTP_429_TOO_MANY_REQUESTS

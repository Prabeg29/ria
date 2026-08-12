import asyncio
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from src.database import db_conn
from src.jobs import extract_resume_text
from src.settings import settings
from tests.conftest import SeededResume


def test_resume_must_be_s3_uploaded_for_text_extraction(
    seed_resume: Callable[[str], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    resume = seed_resume("pending")
    mock_s3_client = MagicMock()
    monkeypatch.setattr("src.jobs.s3_client", mock_s3_client)

    # Act
    asyncio.run(
        extract_resume_text(uuid.UUID(resume.candidate_id), uuid.UUID(resume.id))
    )

    # Assert
    mock_s3_client.get_object.assert_not_called()


def test_empty_resume_after_preprocessing_is_marked_as_failed(
    seed_resume: Callable[[str], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    resume = seed_resume("s3_uploaded")

    mock_body = MagicMock()
    mock_body.read.return_value = b"fake pdf content"
    mock_s3_client = MagicMock()
    mock_s3_client.get_object.return_value = {"Body": mock_body}
    monkeypatch.setattr("src.jobs.s3_client", mock_s3_client)

    mock_page = MagicMock()
    mock_page.get_text.return_value = "some text"
    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_pymupdf = MagicMock()
    mock_pymupdf.open.return_value.__enter__.return_value = mock_doc
    monkeypatch.setattr("src.jobs.pymupdf", mock_pymupdf)

    mock_preprocessor = MagicMock()
    (
        mock_preprocessor.return_value
        .remove_extra_whitespace.return_value
        .normalize_unicode.return_value
        .remove_boilerplates.return_value
        .redact_pii.return_value
        .get_text.return_value
    ) = ""
    monkeypatch.setattr("src.jobs.TextPreprocessor", mock_preprocessor)

    # Act
    with pytest.raises(ValueError):
        asyncio.run(
            extract_resume_text(uuid.UUID(resume.candidate_id), uuid.UUID(resume.id))
        )

    # Assert
    async def _fetch() -> tuple:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT processing_status, processing_failure_remarks FROM ria.resumes WHERE id = %s",
                    (resume.id,),
                )
                row = await cur.fetchone()
                assert row is not None
                return row

    status, remarks = asyncio.run(_fetch())
    assert status == "failed"
    assert remarks == "Resume is empty after preprocessing — marking failed"


def test_raw_text_is_extracted_and_status_advances_to_raw_extracted(
    seed_resume: Callable[[str], SeededResume],
    resume_pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    resume = seed_resume("s3_uploaded")

    mock_body = MagicMock()
    mock_body.read.return_value = resume_pdf_bytes
    mock_s3_client = MagicMock()
    mock_s3_client.get_object.return_value = {"Body": mock_body}
    monkeypatch.setattr("src.jobs.s3_client", mock_s3_client)

    # Act
    asyncio.run(
        extract_resume_text(uuid.UUID(resume.candidate_id), uuid.UUID(resume.id))
    )

    # Assert
    mock_s3_client.get_object.assert_called_once_with(
        Bucket=settings.aws_bucket,
        Key=resume.s3_key,
    )

    async def _fetch() -> tuple:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT processing_status, raw_text FROM ria.resumes WHERE id = %s",
                    (resume.id,),
                )
                row = await cur.fetchone()
                assert row is not None
                return row

    status, raw_text = asyncio.run(_fetch())
    assert status == "raw_extracted"
    assert raw_text

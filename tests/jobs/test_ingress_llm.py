import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai.errors import ServerError
from redis.asyncio import Redis as AsyncRedis
from tenacity import wait_none


from src.jobs import ingest_llm, ingress_llm
from src.settings import settings
from tests.conftest import SeededScrapedJob
from tests.fixtures.stubs import StubJobScraper


def _run_and_capture_events(
    monkeypatch: pytest.MonkeyPatch, request_id: str, resume_text: str, url_hash: str
) -> list[tuple[str, dict[str, Any]]]:
    stream_key = f"analysis:stream:{request_id}"

    async def _run() -> list[tuple[str, dict[str, Any]]]:
        # publish() uses a module-level client whose pooled connections stay
        # bound to whichever event loop first used them; give this run its own
        # client, created and closed within this loop
        client = AsyncRedis(host=settings.redis_host, decode_responses=True)
        monkeypatch.setattr("src.redis.async_redis", client)
        try:
            await ingress_llm(request_id, resume_text, url_hash)
            entries = await client.xrange(stream_key)
            return [
                (fields["type"], json.loads(fields["payload"]))
                for _, fields in entries
            ]
        finally:
            await client.delete(stream_key)
            await client.aclose()

    return asyncio.run(_run())


@pytest.fixture
def mock_gemini_stream(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    async def _chunks() -> AsyncIterator[MagicMock]:
        yield MagicMock(text="Strong alignment with the role.")
        yield MagicMock(text=None)
        yield MagicMock(text=" Gaps in cloud experience.")

    mock = AsyncMock(return_value=_chunks())
    monkeypatch.setattr(
        "src.jobs.gemini_client.aio.models.generate_content_stream", mock
    )
    return mock


def test_llm_ingestion_is_not_proceeded_for_job_details_not_scraped(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_gemini_stream: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345", status="queued")

    # Act
    events = _run_and_capture_events(monkeypatch, request_id, "resume text", scraped_job.url_hash)

    # Assert
    assert mock_gemini_stream.await_count == 0
    assert all(event_type != "delta" for event_type, _ in events)
    assert events[-1] == (
        "done",
        {"status": "failed", "message": "Job details unavailable"},
    )


def test_llm_ingestion_is_not_proceeded_for_archived_job(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_gemini_stream: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job(
        "https://seek.com.au/job/12345",
        status="scraped",
        scraped_data=StubJobScraper._FIXED_JOB,
        is_archived=True,
    )

    # Act
    events = _run_and_capture_events(monkeypatch, request_id, "resume text", scraped_job.url_hash)

    # Assert
    assert mock_gemini_stream.await_count == 0
    assert all(event_type != "delta" for event_type, _ in events)
    assert events[-1] == (
        "done",
        {"status": "failed", "message": "Job details unavailable"},
    )


def test_llm_ingestion_produces_stream_published_to_redis(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_gemini_stream: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job(
        "https://seek.com.au/job/12345",
        status="scraped",
        scraped_data=StubJobScraper._FIXED_JOB,
    )

    # Act
    events = _run_and_capture_events(monkeypatch, request_id, "resume text", scraped_job.url_hash)

    # Assert
    assert mock_gemini_stream.await_count == 1

    deltas = [payload["text"] for event_type, payload in events if event_type == "delta"]
    assert deltas == ["Strong alignment with the role.", " Gaps in cloud experience."]

    assert events[0] == (
        "status",
        {"status": "analyzing", "message": "Reasoning with AI"},
    )
    assert events[-1] == ("done", {"status": "complete"})


def test_transient_gemini_server_error_is_retried_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def _chunks() -> AsyncIterator[MagicMock]:
        yield MagicMock(text="Strong alignment with the role.")

    server_error = ServerError(
        503, {"error": {"message": "Service unavailable", "status": "UNAVAILABLE"}}
    )
    mock_stream = AsyncMock(side_effect=[server_error, server_error, _chunks()])
    monkeypatch.setattr(
        "src.jobs.gemini_client.aio.models.generate_content_stream", mock_stream
    )
    monkeypatch.setattr(ingest_llm.retry, "wait", wait_none())  # type: ignore[attr-defined]

    # Act
    asyncio.run(ingest_llm(resume_text="resume text", job_data={"title": "Engineer"}))

    # Assert
    assert mock_stream.await_count == 3

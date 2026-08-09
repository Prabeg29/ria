import asyncio
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from rq.exceptions import NoSuchJobError

from src.database import db_conn
from src.utils import hash_url
from tests.conftest import SeededResume
from tests.conftest import SeededScrapedJob

pytestmark = pytest.mark.usefixtures("stub_scraper_registry")

JOB_URL = "https://www.seek.com.au/job/12345678"


def test_analyze_returns_422_for_unregistered_domain(client: TestClient) -> None:
    response = client.post(
        f"/resumes/{uuid.uuid4()}/analyze",
        json={"job_url": "https://linkedin.com/jobs/12345"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    errors = response.json()["detail"]
    assert any(e["loc"] == ["body", "job_url"] for e in errors)


def test_analyze_returns_404_for_non_existing_resume(client: TestClient) -> None:
    non_existing_id = str(uuid.uuid4())

    response = client.post(
        f"/resumes/{non_existing_id}/analyze",
        json={"job_url": JOB_URL},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_analyze_returns_404_when_raw_text_is_null(
    client: TestClient,
    seed_resume: Callable[[str, str | None], SeededResume],
) -> None:
    resume = seed_resume("s3_uploaded")

    response = client.post(
        f"/resumes/{resume.id}/analyze",
        json={"job_url": JOB_URL},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_fresh_job_posting_dispatches_scrape_and_ingress(
    client: TestClient,
    seed_resume: Callable[[str, str | None], SeededResume],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_url = f"https://www.seek.com.au/job/fresh-{uuid.uuid4().hex[:8]}"
    url_hash = hash_url(job_url)
    resume = seed_resume("raw_extracted", raw_text="Experienced software engineer")

    mock_scrape = MagicMock()
    mock_scrape.delay.return_value = "scrape-job-id"
    mock_ingress = MagicMock()
    monkeypatch.setattr("src.api.scrape_job_details", mock_scrape)
    monkeypatch.setattr("src.api.ingress_llm", mock_ingress)

    try:
        response = client.post(
            f"/resumes/{resume.id}/analyze",
            json={"job_url": job_url},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert "job_id" in response.json()
        mock_scrape.delay.assert_called_once()
        mock_ingress.delay.assert_called_once()
        assert mock_scrape.delay.call_args.args[0] == response.json()["job_id"]
        dependency = mock_ingress.delay.call_args.kwargs["depends_on"]
        assert dependency.dependencies == ["scrape-job-id"]
        assert mock_ingress.delay.call_args.args[0] == response.json()["job_id"]
    finally:
        async def _cleanup() -> None:
            async with db_conn() as conn:
                await conn.execute(
                    "DELETE FROM ria.scraped_jobs WHERE url_hash = %s;",
                    (url_hash,),
                )

        asyncio.run(_cleanup())


def test_cached_job_posting_skips_scrape_dispatches_ingress(
    client: TestClient,
    seed_resume: Callable[[str, str | None], SeededResume],
    seed_scraped_job: Callable[[str, str], SeededScrapedJob],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — row exists with terminal status; last_scraped_at is NULL so the
    # ON CONFLICT WHERE condition (last_scraped_at < NOW() - 72h) evaluates to
    # NULL (falsy), skipping the re-scrape update and returning no row.
    job_url = f"https://www.seek.com.au/job/cached-{uuid.uuid4().hex[:8]}"
    resume = seed_resume("raw_extracted", raw_text="Experienced software engineer")
    seed_scraped_job(job_url, "scraped")

    mock_scrape = MagicMock()
    mock_ingress = MagicMock()
    mock_job_cls = MagicMock()
    mock_job_cls.fetch.side_effect = NoSuchJobError
    monkeypatch.setattr("src.api.scrape_job_details", mock_scrape)
    monkeypatch.setattr("src.api.ingress_llm", mock_ingress)
    monkeypatch.setattr("src.api.Job", mock_job_cls)

    response = client.post(
        f"/resumes/{resume.id}/analyze",
        json={"job_url": job_url},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert "job_id" in response.json()
    mock_scrape.delay.assert_not_called()
    mock_ingress.delay.assert_called_once()
    assert mock_ingress.delay.call_args.kwargs["depends_on"] is None


@pytest.mark.rate_limit
def test_analyze_returns_429_beyond_2_requests_per_minute(
    client: TestClient,
    seed_resume: Callable[[str, str | None], SeededResume],
    seed_scraped_job: Callable[[str, str], SeededScrapedJob],
    monkeypatch: pytest.MonkeyPatch,
    flush_rate_limit: None,
) -> None:
    """The 3rd request within the fixed window must be rejected with 429; the
    first 2 must dispatch successfully (cached Job Posting path, so no scrape
    is enqueued and the seeded rows are torn down by their fixtures)."""
    # Arrange
    job_url = f"https://www.seek.com.au/job/ratelimit-{uuid.uuid4().hex[:8]}"
    resume = seed_resume("raw_extracted", raw_text="Experienced software engineer")
    seed_scraped_job(job_url, "scraped")

    mock_job_cls = MagicMock()
    mock_job_cls.fetch.side_effect = NoSuchJobError
    monkeypatch.setattr("src.api.scrape_job_details", MagicMock())
    monkeypatch.setattr("src.api.ingress_llm", MagicMock())
    monkeypatch.setattr("src.api.Job", mock_job_cls)

    # Act
    responses = [
        client.post(
            f"/resumes/{resume.id}/analyze",
            json={"job_url": job_url},
        )
        for _ in range(3)
    ]

    # Assert
    assert all(
        response.status_code == status.HTTP_202_ACCEPTED
        for response in responses[:2]
    )
    assert responses[2].status_code == status.HTTP_429_TOO_MANY_REQUESTS


def test_inflight_job_posting_skips_scrape_reuses_existing_job(
    client: TestClient,
    seed_resume: Callable[[str, str | None], SeededResume],
    seed_scraped_job: Callable[[str, str], SeededScrapedJob],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — row exists with in-flight status; ON CONFLICT WHERE condition
    # excludes 'queued'/'scraping', so no update fires and the existing RQ job
    # is fetched via Job.fetch to be passed as the ingress_llm dependency.
    job_url = f"https://www.seek.com.au/job/inflight-{uuid.uuid4().hex[:8]}"
    resume = seed_resume("raw_extracted", raw_text="Experienced software engineer")
    seed_scraped_job(job_url, "queued")

    mock_scrape = MagicMock()
    mock_ingress = MagicMock()
    mock_existing_rq_job = "existing-job-id"
    mock_job_cls = MagicMock()
    mock_job_cls.fetch.return_value = mock_existing_rq_job
    monkeypatch.setattr("src.api.scrape_job_details", mock_scrape)
    monkeypatch.setattr("src.api.ingress_llm", mock_ingress)
    monkeypatch.setattr("src.api.Job", mock_job_cls)

    response = client.post(
        f"/resumes/{resume.id}/analyze",
        json={"job_url": job_url},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert "job_id" in response.json()
    mock_scrape.delay.assert_not_called()
    mock_ingress.delay.assert_called_once()
    dependency = mock_ingress.delay.call_args.kwargs["depends_on"]
    assert dependency.dependencies == [mock_existing_rq_job]
    assert mock_ingress.delay.call_args.args[0] == response.json()["job_id"]

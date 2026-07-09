import asyncio
import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.database import db_conn
from src.jobs import scrape_job_details
from tests.conftest import SeededScrapedJob
from tests.fixtures.stubs import StubJobScraper


def _fetch_scraped_job(job_id: str) -> dict[str, Any]:
    async def _fetch() -> dict[str, Any]:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                        SELECT status, scraped_data, is_archived, last_scraped_at
                        FROM ria.scraped_jobs
                        WHERE id = %s;
                    """,
                    (job_id,),
                )
                row = await cur.fetchone()
                assert row is not None
                return {
                    "status": row[0],
                    "scraped_data": row[1],
                    "is_archived": row[2],
                    "last_scraped_at": row[3],
                }

    return asyncio.run(_fetch())


@pytest.fixture
def mock_playwright(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock_page = AsyncMock()
    mock_page.goto.return_value = MagicMock(status=200)

    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page

    playwright = MagicMock()
    playwright.firefox.connect = AsyncMock(return_value=mock_browser)

    playwright_cm = AsyncMock()
    playwright_cm.__aenter__.return_value = playwright

    monkeypatch.setattr("src.jobs.async_playwright", MagicMock(return_value=playwright_cm))
    return mock_page


def test_status_is_published_as_scraping_initially(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_playwright: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345")

    mock_publish = AsyncMock()
    monkeypatch.setattr("src.jobs.publish", mock_publish)

    # Act
    asyncio.run(
        scrape_job_details(
            request_id=request_id,
            job_scraper=StubJobScraper(),
            normalized_url=scraped_job.url,
            url_hash=scraped_job.url_hash,
        )
    )

    # Assert
    assert mock_publish.await_args_list[0] == call(
        request_id,
        "status",
        {"status": "scraping", "message": "Accessing job url..."},
    )


def test_scraped_data_is_persisted_on_success(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_playwright: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345")

    monkeypatch.setattr("src.jobs.publish", AsyncMock())

    # Act
    asyncio.run(
        scrape_job_details(
            request_id=request_id,
            job_scraper=StubJobScraper(),
            normalized_url=scraped_job.url,
            url_hash=scraped_job.url_hash,
        )
    )

    # Assert
    row = _fetch_scraped_job(scraped_job.id)
    assert row["scraped_data"] == StubJobScraper._FIXED_JOB


def test_status_transitions_to_scraped_on_success(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_playwright: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345")

    monkeypatch.setattr("src.jobs.publish", AsyncMock())

    # Act
    asyncio.run(
        scrape_job_details(
            request_id=request_id,
            job_scraper=StubJobScraper(),
            normalized_url=scraped_job.url,
            url_hash=scraped_job.url_hash,
        )
    )

    # Assert
    row = _fetch_scraped_job(scraped_job.id)
    assert row["status"] == "scraped"
    assert row["is_archived"] is False
    assert row["last_scraped_at"] is not None


def test_404_marks_job_scraped_and_archived(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_playwright: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345")

    monkeypatch.setattr("src.jobs.publish", AsyncMock())
    mock_playwright.goto.return_value = MagicMock(status=404)

    # Act
    asyncio.run(
        scrape_job_details(
            request_id=request_id,
            job_scraper=StubJobScraper(),
            normalized_url=scraped_job.url,
            url_hash=scraped_job.url_hash,
        )
    )

    # Assert
    row = _fetch_scraped_job(scraped_job.id)
    assert row["status"] == "scraped"
    assert row["is_archived"] is True
    assert row["scraped_data"] is None
    assert row["last_scraped_at"] is not None


def test_transient_error_does_not_mark_job_as_failed(
    seed_scraped_job: Callable[..., SeededScrapedJob],
    mock_playwright: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    request_id = str(uuid.uuid4())
    scraped_job = seed_scraped_job("https://seek.com.au/job/12345")

    monkeypatch.setattr("src.jobs.publish", AsyncMock())
    mock_playwright.goto.side_effect = PlaywrightTimeoutError("Timeout 30000ms exceeded.")

    # Act
    with pytest.raises(PlaywrightTimeoutError):
        asyncio.run(
            scrape_job_details(
                request_id=request_id,
                job_scraper=StubJobScraper(),
                normalized_url=scraped_job.url,
                url_hash=scraped_job.url_hash,
            )
        )

    # Assert
    async def _fetch() -> str:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status FROM ria.scraped_jobs WHERE id = %s",
                    (scraped_job.id,),
                )
                row = await cur.fetchone()
                assert row is not None
                return row[0]

    assert asyncio.run(_fetch()) == "scraping"

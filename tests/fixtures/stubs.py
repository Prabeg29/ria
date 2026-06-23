from typing import Any

from src.job_scraper import JobScraper


class StubJobScraper(JobScraper):
    _FIXED_JOB: dict[str, Any] = {
        "title": "Senior Software Engineer",
        "company": "Acme Corp",
        "location": "Sydney NSW",
        "details": ["Full-time position. 5+ years experience required."],
    }

    @property
    def _allowed_query_params(self) -> set[str]:
        return set()

    def normalize(self, url: str) -> str:
        return url

    async def extract(self, page: Any) -> dict[str, Any]:
        return self._FIXED_JOB


class StubScraperRegistry:
    @classmethod
    def resolve(cls, url: str) -> StubJobScraper:
        return StubJobScraper()

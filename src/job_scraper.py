from abc import ABC, abstractmethod
from typing import Any


class JobScraper(ABC):
    @abstractmethod
    async def extract(self, page) -> dict:
        pass


class SeekJobScraper(JobScraper):
    async def extract(self, page) -> dict[str, Any]:
        return {
            "title": await page.locator('h1[data-automation="job-detail-title"]').inner_text(),
            "company": await page.locator('span[data-automation="advertiser-name"]').inner_text(),
            "location": await page.locator('span[data-automation="job-detail-location"]').inner_text(),
            "details": await page.locator('div[data-automation="jobAdDetails"]').all_text_contents(),
        }


class LinkedinJobScraper(JobScraper):
    async def extract(self, page) -> dict:
        pass


class ScraperRegistry:
    _registry: dict[str, type[JobScraper]] = {}

    @classmethod
    def register(cls, domain: str, scraper: type[JobScraper]) -> None:
        cls._registry[domain] = scraper

    @classmethod
    def resolve(cls, domain: str) -> JobScraper:
        for key, scraper_class in cls._registry.items():
            if key in domain:
                return scraper_class()
        raise ValueError(f"No registered scraper for domain: {domain}")

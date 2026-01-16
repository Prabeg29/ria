from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse


class JobScraper(ABC):
    @abstractmethod
    async def extract(self, page) -> dict[str, str]:
        pass


class SeekJobScraper(JobScraper):
    async def extract(self, page) -> dict[str, Any]:
        title = await page.locator('h1[data-automation="job-detail-title"]').inner_text()
        company = await page.locator('span[data-automation="advertiser-name"]').inner_text()
        location = await page.locator('span[data-automation="job-detail-location"]').inner_text()
        details = await page.locator('div[data-automation="jobAdDetails"]').all_text_contents()

        return {
            "title": title, 
            "company": company,
            "location": location,
            "details": details,
        }


class ScraperRegistry:
    _registry: dict[str, type[JobScraper]] = {}

    @classmethod
    def register(cls, domain: str, scraper: type[JobScraper]) -> None:
        cls._registry[domain] = scraper

    @classmethod
    def resolve(cls, domain: str) -> JobScraper:
        parsed_domain = urlparse(domain)
        hostname = parsed_domain.netloc

        if not hostname:
            raise ValueError("URL has no valid hostname")

        for key, scraper_class in cls._registry.items():
            if key in hostname:
                return scraper_class()

        raise ValueError(f"No registered scraper for domain: {domain}")


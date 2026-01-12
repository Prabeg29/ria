from pathlib import Path

from fastapi import Request

from .database import db_conn
from .job_scraper import ScraperRegistry


def get_resume_upload_dir(request: Request) -> Path:
    return request.app.state.resume_upload_dir


async def get_db_connection():
    async with db_conn() as conn:
        yield conn


def get_scraper_registry(request: Request) -> ScraperRegistry:
    return request.app.state.scraper_registry

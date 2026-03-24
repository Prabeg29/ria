from fastapi import Header, HTTPException, Request, status

from .database import db_conn
from .job_scraper import ScraperRegistry


def verify_content_hash_header(
    x_content_hash: str | None = Header(default=None, description="SHA-256 hash of the file content")
) -> str:
    if not x_content_hash or not x_content_hash.strip():
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Missing required header: X-Content-Hash",
        )
    return x_content_hash.strip()


async def get_db_connection():
    async with db_conn() as conn:
        yield conn


def get_scraper_registry(request: Request) -> ScraperRegistry:
    return request.app.state.scraper_registry

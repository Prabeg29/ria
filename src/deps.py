from fastapi import Depends, Header, HTTPException, Request, status

from .database import db_conn
from .job_scraper import ScraperRegistry
from .models import Candidate
from .utils import hash_url


async def get_db_connection():
    async with db_conn() as conn:
        yield conn


async def get_authenticated_candidate(
    x_api_key: str | None = Header(default=None),
    db_conn=Depends(get_db_connection)
) -> Candidate:
    if x_api_key is None or x_api_key.strip() is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required header: X-API-KEY",
        )

    async with db_conn.cursor() as cur:
        await cur.execute(
            """
                SELECT tenants.id, tenants.email
                FROM ria.api_keys
                JOIN ria.tenants ON tenants.id = api_keys.tenant_id
                WHERE api_keys.key_hash = %s
            """,
            (hash_url(x_api_key),)
        )

        candidate_row = await cur.fetchone()
    
    if candidate_row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )
    
    return Candidate(id=candidate_row[0], email=candidate_row[1])


def verify_content_hash_header(
    x_content_hash: str | None = Header(
        default=None, description="SHA-256 hash of the file content"
    )
) -> str:
    if not x_content_hash or not x_content_hash.strip():
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Missing required header: X-Content-Hash",
        )
    return x_content_hash.strip()


def get_scraper_registry(request: Request) -> ScraperRegistry:
    return request.app.state.scraper_registry

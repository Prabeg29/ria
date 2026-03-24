#----------------------------------
# Followed layered architecture
#----------------------------------
import json
import uuid

from dataclasses import dataclass

import boto3

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from psycopg import sql
from psycopg.rows import class_row
from rq.exceptions import NoSuchJobError
from rq.job import Job

from .deps import (
    get_db_connection,
    get_scraper_registry,
    verify_content_hash_header,
)
from .logger import REQUEST_ID_CTX, logger
from .jobs import (
    ingress_llm,
    process_and_save_resume,
    scrape_job_details,
)
from .models import Resume
from .settings import settings
from .redis import async_redis
from .utils import hash_url


router = APIRouter(prefix="")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key,
    aws_secret_access_key=settings.aws_secret_key,
    region_name=settings.aws_region,
)

VALID_FILE_FORMATS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
CHUNK_SIZE = 1024 * 1024  # 1MB


#----------------------------------------------------
# Add retry with exponential backoff and jitter 
#----------------------------------------------------
def generate_presigned_url(s3_client, client_method: str, params: dict[str, str], expires_in: int):
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod=client_method,
            Params=params,
            ExpiresIn=expires_in
        )

        return url
    except Exception:
        raise


@dataclass
class ResumeUploadSchema:
    filename: str
    size: int
    content_type: str


@router.post("/resumes/upload/init")
async def upload_resume(
    payload: ResumeUploadSchema,
    content_hash: str = Depends(verify_content_hash_header),
    db_conn=Depends(get_db_connection),
):
    #----------------------------------------------------
    # Move validations a step-up and away from controller
    #----------------------------------------------------
    if not payload.filename or not payload.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename is required",
        )

    if payload.content_type not in VALID_FILE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid file format. Only PDF and DOCX are allowed.",
        )

    if payload.size and payload.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File size exceeds the maximum limit of 2MB.",
        )

    resume = Resume(filename=payload.filename,)
    resume.s3_url = f"resumes/{resume.id}-{payload.filename}"

    async with db_conn.cursor() as cur:
        await cur.execute(
            sql.SQL(
                """
                    INSERT INTO ria.resumes (
                        id,
                        filename,
                        content_hash,
                        s3_url,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (content_hash) DO UPDATE
                    SET updated_at = NOW()
                    WHERE resumes.upload_status = 'pending'
                    AND (
                            resumes.last_upload_presigned_url_generated_at is NULL
                            OR
                            resumes.last_upload_presigned_url_generated_at < NOW() - INTERVAL '3 minutes'
                        )
                    RETURNING id;
                """
            ),
            (
                resume.id,
                resume.filename,
                content_hash,
                resume.s3_url,
            ),
        )

        row = await cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has been previously uploaded, skipping processing",
        )
    
    url = generate_presigned_url(
        s3_client=s3_client,
        client_method="put_object",
        params={
            "Bucket": settings.aws_bucket,
            "Key": resume.s3_url,
            "ContentType": payload.content_type,
        },
        expires_in=180, # Set a config
    )

    async with db_conn as aconn:
        await aconn.execute(
            query="""
                UPDATE ria.resumes
                SET last_upload_presigned_url_generated_at = NOW(),
                    updated_at = NOW()
                WHERE content_hash = %s;
            """,
            params=(content_hash,)
        )

    return {"id": resume.id, "upload_url": url}


@dataclass
class ResumeUploadCompleteSchema:
    resume_id: str


# @TODO: Create a dummy data in db and test this
@router.post("/resumes/upload/complete")
async def update_resume(
    payload: ResumeUploadCompleteSchema,
    db_conn=Depends(get_db_connection),
):  
    async with db_conn.cursor() as aconn:
        await aconn.execute("""
            SELECT
                resumes.id,
                resumes.parsed_data
            FROM resumes
            WHERE resumes.id = %s
            AND resumes.upload_status = 'pending'
            AND resumes.parsed_data IS NULL
        """,
            (payload.resume_id,),
        )
        resume = await aconn.fetchone()

    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No resume found for id: {payload.resume_id}",
        )

    async with db_conn as aconn:
        await aconn.execute(
            query="""
                UPDATE ria.resumes
                SET upload_status = 'completed',
                    updated_at = NOW()
                WHERE id = %s;
            """,
            params=(payload.resume_id,)
        )
    
    process_and_save_resume.delay( # type: ignore
        REQUEST_ID_CTX.get(),
        payload.resume_id,
    )


@dataclass
class ResumeAnalyzeSchema:
    job_url: str


@router.post("/resumes/{resume_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_resume(
    resume_id: str,
    payload: ResumeAnalyzeSchema,
    db_conn=Depends(get_db_connection),
    scraper_registry=Depends(get_scraper_registry)
):
    async with db_conn.cursor(row_factory=class_row(Resume)) as cur:
        await cur.execute("""
                SELECT
                    resumes.id,
                    resumes.raw_text
                FROM resumes
                WHERE resumes.id = %s
            """,
            (resume_id,),
            )
            
        resume = await cur.fetchone()

    if resume is None:
        raise Exception(f"No resume found with ID {resume_id}.")
    
    job_scraper = scraper_registry.resolve(payload.job_url)
    normalized_url = job_scraper.normalize(payload.job_url)
    url_hash = hash_url(normalized_url)

    async with db_conn.cursor() as cur:
        await cur.execute(
            query="""
                INSERT INTO scraped_jobs (
                    id,
                    normalized_url,
                    url_hash,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (url_hash)
                DO UPDATE SET
                    status = 'queued',
                    updated_at = EXCLUDED.updated_at
                    WHERE scraped_jobs.last_scraped_at < NOW() - INTERVAL '24 hours'
                    AND scraped_jobs.is_archived = false
                    OR scraped_jobs.status NOT IN ('queued', 'scraping')
                RETURNING id;
            """, 
        params=(str(uuid.uuid4()), normalized_url, url_hash))

        row = await cur.fetchone()

    scrape_job = None

    if row:
        logger.info(
            "Queued scraping job details",
            extra={
                "raw_job_url": payload.job_url,
                "normalized_job_url": normalized_url,
                "url_hash": url_hash,
            }
        )

        scrape_job = scrape_job_details.delay( # type: ignore
            REQUEST_ID_CTX.get(),
            job_scraper,
            normalized_url,
            url_hash,
            job_id=url_hash,
        )
    else:
        try:
            scrape_job = Job.fetch(url_hash, connection=settings.redis_conn)
        except NoSuchJobError:
            pass

    logger.info(
        "Queued analyzing resume against job details",
        extra={
            "raw_job_url": payload.job_url,
            "normalized_job_url": normalized_url,
            "url_hash": url_hash,
        }
    )

    ingress_llm.delay( # type: ignore
        REQUEST_ID_CTX.get(),
        resume.raw_text,
        url_hash,
        depends_on=scrape_job
    )

    return {"status": "queued", "job_id": REQUEST_ID_CTX.get()}


def build_sse_event(data: dict, event_type: str = "message") -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def analysis_generator(job_id: str):
    stream_key = f"analysis:stream:{job_id}"
    last_id = "0-0"
    yield ":\n\n"

    yield build_sse_event({"status": "listening"}, "status")

    while True:
        messages = await async_redis.xread(
            {stream_key: last_id},
            block=5000,
            count=10,
        )

        if not messages:
            continue

        entries = messages[0][1]

        for message_id, fields in entries:
            last_id = message_id

            event_type = fields["type"]
            payload = json.loads(fields["payload"])

            yield build_sse_event(payload, event_type)

            if event_type == "done":                    
                return


@router.get("/analysis/{job_id}/stream")
async def stream_job_analysis(job_id: str):
    return StreamingResponse(
        analysis_generator(job_id=job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

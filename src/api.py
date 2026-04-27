import json
import uuid

from botocore.exceptions import ClientError
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
from .schemas import (
    ResumeAnalyzeSchema,
    ResumeUploadPayload,
    ResumeUploadCompleteSchema,
    ResumeUploadInitResponse,
)
from .settings import settings
from .redis import async_redis
from .utils import hash_url, s3_client


router = APIRouter(prefix="")


@router.post(
    "/resumes/upload/init",
    response_model=ResumeUploadInitResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiates a resume upload by creating a record and generating an S3 URL.",
    description="""Registers the resume metadata in the database using an upsert strategy on the
    content hash. If the resume already exists and is not in a 'pending' state, or
    if a presigned URL was generated recently, the request is rejected to prevent
    duplicates."""
)
async def upload_resume(
    payload: ResumeUploadPayload,
    content_hash: str = Depends(verify_content_hash_header),
    db_conn=Depends(get_db_connection),
):
    """
    Args:
        payload: The resume metadata including filename and content type.
        content_hash: The SHA-256 hash of the file content from the header.
        db_conn: The asynchronous database connection.

    Returns:
        A dictionary containing the resume ID and the S3 presigned POST URL.

    Raises:
        HTTPException: If the file has been previously uploaded or if an upload
            is already in progress for this content hash.
    """
    resume = Resume(
        filename=payload.filename,
    )
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
                    RETURNING id, s3_url;
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

    url = s3_client.generate_presigned_post(
        Bucket=settings.aws_bucket,
        Key=row[1],
        Fields={"Content-Type": payload.content_type},
        Conditions=[
            ["eq", "$Content-Type", payload.content_type],
            ["content-length-range", 50, 1024 * 1024],
        ],
        ExpiresIn=settings.aws_s3_presigned_url_expiresin,
    )

    await db_conn.execute(
        query="""
            UPDATE ria.resumes
            SET last_upload_presigned_url_generated_at = NOW(),
                updated_at = NOW()
            WHERE content_hash = %s;
        """,
        params=(content_hash,),
    )

    return ResumeUploadInitResponse(id=row[0], upload_url=url)


@router.post("/resumes/upload/complete")
async def update_resume(
    payload: ResumeUploadCompleteSchema,
    db_conn=Depends(get_db_connection),
):
    lock_key = f"resume:complete:{payload.resume_id}"
    acquired = settings.redis_conn.set(lock_key, 1, ex=30, nx=True)

    try:
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Upload completion already in progress for this resume.",
            )

        async with db_conn.cursor() as aconn:
            await aconn.execute(
                """
                SELECT
                    resumes.id,
                    resumes.s3_url
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

        try:
            s3_client.head_object(Bucket=settings.aws_bucket, Key=resume[1])
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("404", "NoSuchKey"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="File not found in S3 — the upload may not have completed.",
                )

        async with db_conn.cursor() as cur:
            await cur.execute(
                query="""
                    UPDATE ria.resumes
                    SET upload_status = 'completed',
                        updated_at = NOW()
                    WHERE id = %s
                    AND resumes.upload_status='pending'
                    RETURNING id;
                """,
                params=(payload.resume_id,),
            )

            updated = await cur.fetchone()

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resume was already marked as completed.",
            )

        process_and_save_resume.delay(payload.resume_id)  # type: ignore
    finally:
        settings.redis_conn.delete(lock_key)

    """
    See long polling vs sse 
    """
    return {"message": "Resume sent for LLM parsing"}


@router.post("/resumes/{resume_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_resume(
    resume_id: str,
    payload: ResumeAnalyzeSchema,
    db_conn=Depends(get_db_connection),
    scraper_registry=Depends(get_scraper_registry),
):
    async with db_conn.cursor(row_factory=class_row(Resume)) as cur:
        await cur.execute(
            """
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No resume found with ID {resume_id}.",
        )

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
            params=(str(uuid.uuid4()), normalized_url, url_hash),
        )

        row = await cur.fetchone()

    scrape_job = None

    if row:
        logger.info(
            "Queued scraping job details",
            extra={
                "raw_job_url": payload.job_url,
                "normalized_job_url": normalized_url,
                "url_hash": url_hash,
            },
        )

        scrape_job = scrape_job_details.delay(  # type: ignore
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
        },
    )

    ingress_llm.delay(  # type: ignore
        REQUEST_ID_CTX.get(), resume.raw_text, url_hash, depends_on=scrape_job
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
        },
    )

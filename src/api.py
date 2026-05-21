import json
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    extract_resume_text,
    parse_resume_with_llm,
    ingress_llm,
    scrape_job_details,
)
from .models import Resume
from .schemas import (
    ResumeAnalyzeRequest,
    ResumeUploadRequest,
    ResumeUploadCompleteRequest,
    ResumeUploadInitResponse,
)
from .settings import settings
from .redis import async_redis
from .utils import hash_url, rate_limiter, s3_client


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
@rate_limiter.limit("20/minute")
async def upload_resume(
    request: Request,
    response: Response,
    payload: ResumeUploadRequest,
    content_hash: str = Depends(verify_content_hash_header),
    db_conn=Depends(get_db_connection),
):
    """
    Args:
        request: Request object from FastAPI, explicit declaration for SlowAPI
        response: Response object from FastAPI, explicit declaration for SlowAPI
        payload: The resume metadata including filename, size, and content type.
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
                    WHERE resumes.processing_status = 'pending'
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

        resume = await cur.fetchone()

    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has been previously uploaded, skipping processing",
        )

    [resume_id, s3_key] = resume

    url = s3_client.generate_presigned_post(
        Bucket=settings.aws_bucket,
        Key=s3_key,
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

    return ResumeUploadInitResponse(id=resume_id, upload_url=url)


@router.post(
    "/resumes/upload/complete",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispatches the resume uploaded for LLM extraction",
    description="""Validates resumes upload through DB and S3 checks.
    Dispatches the resumes with valid upload for LLM extraction
    """
)
@rate_limiter.limit("5/minute")
async def update_resume(
    request: Request,
    response: Response,
    payload: ResumeUploadCompleteRequest,
    db_conn=Depends(get_db_connection),
):
    """
    Args:
        request: Request object from FastAPI, explicit declaration for SlowAPI
        response: Response object from FastAPI, explicit declaration for SlowAPI
        payload: The resume metadata including id.
        db_conn: The asynchronous database connection.

    Returns:
        Success message

    Raises:
        HTTPException: If the file has been previously dispatched or if there was no upload.
    """
    async with db_conn.cursor() as aconn:
        await aconn.execute(
            """
                SELECT
                    resumes.id,
                    resumes.s3_key,
                    resumes.processing_status
                FROM resumes
                WHERE resumes.id = %s
                AND resume.processing_status NOT IN ("failed", "llm_parsed")
                FOR UPDATE;
            """,
            (payload.resume_id,),
        )
        resume = await aconn.fetchone()

    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No resume found for id: {payload.resume_id}",
        )
    
    [resume_id, s3_key, processing_status] = resume
    
    if processing_status == 'pending':
        try:
            s3_client.head_object(Bucket=settings.aws_bucket, Key=s3_key)

            await db_conn.execute(
                query="""
                    UPDATE ria.resumes
                    SET processing_status = 's3_uploaded',
                        updated_at = NOW()
                    WHERE id = %s;
                """,
                params=(payload.resume_id,),
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("404", "NoSuchKey"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="File not found in S3 — the upload may not have completed.",
                )
            raise

    extract_job = (
        None
        if processing_status == "raw_extracted" 
        else extract_resume_text.delay(resume_id)  # type: ignore
    )

    # On Date: 2026-05-19, cannot think of any feature how parsing the resume
    # content as JSON would add any value. If you think this is required do
    # update the rate limit for the endpoint
    #
    # parse_resume_with_llm.delay( # type: ignore
    #     resume_id,
    #     depends_on=extract_job,
    # )
    return {"message": "Resume sent for further processing"}


@router.post(
    "/resumes/{resume_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    summary="",
    description="""""",
)
@rate_limiter.limit("2/minute")
async def analyze_resume(
    request: Request,
    response: Response,
    resume_id: uuid.UUID,
    payload: ResumeAnalyzeRequest,
    db_conn=Depends(get_db_connection),
    scraper_registry=Depends(get_scraper_registry),
):
    """
    Args:
        request: Request object from FastAPI, explicit declaration for SlowAPI
        response: Response object from FastAPI, explicit declaration for SlowAPI
        payload: The job url to analyze resume against
        db_conn: The asynchronous database connection.
        scraper_registry: Registry storing all scraper class, resolved to the one based on URL at run time

    Returns:
        Success message

    Raises:
        HTTPException 
    """
    async with db_conn.cursor(row_factory=class_row(Resume)) as cur:
        await cur.execute(
            """
                SELECT
                    resumes.id,
                    resumes.raw_text
                FROM resumes
                WHERE resumes.id = %s
                AND resumes.raw_text IS NOT NULL;
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
                    WHERE scraped_jobs.last_scraped_at < NOW() - INTERVAL '72 hours'
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

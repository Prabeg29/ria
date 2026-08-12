import json
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from psycopg import sql
from psycopg.rows import class_row
from rq.exceptions import NoSuchJobError
from rq.job import Dependency, Job

from .deps import (
    get_db_connection,
    get_authenticated_candidate,
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
from .models import Candidate, Resume
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
    dependencies=[Depends(verify_content_hash_header)],
    summary="Initiate a resume upload",
    description="""Registers the resume metadata in the database using an upsert on the content hash
    and returns an S3 presigned POST URL for the client to upload the file directly.

    Deduplication: If a resume with the same content hash already exists and has moved past the
    'pending' state, or a presigned URL was generated within the last 3 minutes, the request
    is rejected with 400 to prevent duplicate uploads.

    The presigned URL enforces a content-type match and a file size between 1KB and 10KB.
    It expires after the configured TTL (aws_s3_presigned_url_expiresin).""",
)
@rate_limiter.limit("20/minute")
async def upload_resume(
    request: Request,
    response: Response,
    payload: ResumeUploadRequest,
    candidate: Candidate = Depends(get_authenticated_candidate),
    content_hash: str = Depends(verify_content_hash_header),
    db_conn=Depends(get_db_connection),
):
    resume = Resume(
        filename=payload.filename,
    )
    resume.s3_key = f"resumes/{resume.id}-{payload.filename}"

    async with db_conn.cursor() as cur:
        await cur.execute(
            sql.SQL(
                """
                    INSERT INTO ria.resumes (
                        id,
                        candidate_id,
                        filename,
                        content_hash,
                        s3_key,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (candidate_id, content_hash) DO UPDATE
                    SET updated_at = NOW()
                    WHERE resumes.processing_status = 'pending'
                    AND (
                            resumes.last_upload_presigned_url_generated_at is NULL
                            OR
                            resumes.last_upload_presigned_url_generated_at < NOW() - (%s)::interval
                        )
                    RETURNING id, s3_key;
                """
            ),
            (
                resume.id,
                candidate.id,
                resume.filename,
                content_hash,
                resume.s3_key,
                f"{settings.aws_s3_presigned_url_expiresin} seconds"
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
            ["content-length-range", 1024, 10 * 1024],
        ],
        ExpiresIn=settings.aws_s3_presigned_url_expiresin,
    )

    await db_conn.execute(
        query="""
            UPDATE ria.resumes
            SET last_upload_presigned_url_generated_at = NOW(),
                updated_at = NOW()
            WHERE content_hash = %s
            AND candidate_id = %s;
        """,
        params=(content_hash, candidate.id),
    )

    return ResumeUploadInitResponse(id=resume_id, upload_url=url)


@router.post(
    "/resumes/upload/complete",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Confirm upload and dispatch resume for text extraction",
    description="""Called by the client after the file has been uploaded to S3 via the presigned URL.

    Verification: Looks up the resume by ID, skipping any that are already in a terminal
    state ('failed' or 'llm_parsed'). For resumes still in 'pending', an S3 HEAD check
    confirms the object exists; if not, returns 422.

    Dispatch: Once verified, the processing status is moved to 's3_uploaded' and the resume
    is enqueued for raw text extraction (extract_resume_text). Resumes already at
    'raw_extracted' skip the extraction step.

    Returns 404 if no resume matches the given ID or all matching resumes are in terminal states.""",
)
@rate_limiter.limit("5/minute")
async def update_resume(
    request: Request,
    response: Response,
    payload: ResumeUploadCompleteRequest,
    candidate: Candidate = Depends(get_authenticated_candidate),
    db_conn=Depends(get_db_connection),
):
    async with db_conn.cursor() as aconn:
        await aconn.execute(
            """
                SELECT
                    resumes.id,
                    resumes.s3_key,
                    resumes.processing_status
                FROM resumes
                WHERE resumes.id = %s
                AND resumes.candidate_id = %s
                AND resumes.processing_status NOT IN ('failed', 'llm_parsed')
                FOR UPDATE;
            """,
            (payload.resume_id, candidate.id),
        )
        resume = await aconn.fetchone()

    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
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
                    WHERE id = %s
                    AND candidate_id = %s;
                """,
                params=(payload.resume_id, candidate.id),
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("404", "NoSuchKey"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="File not found in S3 — the upload may not have completed.",
                )
            raise

    extract_job = (
        None
        if processing_status == "raw_extracted" 
        else extract_resume_text.delay(candidate.id, resume_id)  # type: ignore
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
    "/resumes/{resume_id}/analyses",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Analyze a resume against a job posting",
    description="""Accepts a job URL, scrapes the posting (or reuses a recent scrape), and queues
    an LLM analysis comparing the resume against the job requirements.

    Scraping: The job URL is normalized and hashed. If no recent scrape exists (within 72 hours)
    or the previous scrape is not currently in-flight, a new scrape job is dispatched via
    Playwright. Otherwise the existing scraped data or in-progress job is reused.

    Analysis: Once scraping completes (or is skipped), the ingress_llm job is enqueued with a
    dependency on the scrape job. Results are streamed to the client via SSE on the
    /analysis/{job_id}/stream endpoint.

    Returns 404 if no resume with extracted text is found for the given ID.""",
)
@rate_limiter.limit("2/minute")
async def analyze_resume(
    request: Request,
    response: Response,
    resume_id: uuid.UUID,
    payload: ResumeAnalyzeRequest,
    candidate: Candidate = Depends(get_authenticated_candidate),
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
                AND resumes.candidate_id = %s
                AND resumes.raw_text IS NOT NULL;
            """,
            (resume_id, candidate.id),
        )

        resume = await cur.fetchone()

    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    analysis_id = str(uuid.uuid4())
    settings.redis_conn.set(f"analysis:owner:{analysis_id}", str(candidate.id))

    job_scraper = scraper_registry.resolve(payload.job_url)
    normalized_url = job_scraper.normalize(payload.job_url)
    url_hash = hash_url(normalized_url)

    # We are hashing the URL but that does not dedup the job posting
    # The same posting can be on Blackbird as well as OIF
    # Better we hash the job posting content 

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
                    WHERE scraped_jobs.is_archived = false
                    AND (
                        scraped_jobs.status = 'failed'
                        OR (
                            scraped_jobs.status = 'scraped'
                            AND scraped_jobs.last_scraped_at < NOW() - INTERVAL '72 hours'
                        )
                        OR (
                            scraped_jobs.status IN ('queued', 'scraping')
                            AND scraped_jobs.updated_at < NOW() - INTERVAL '15 minutes'
                        )
                    )
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
            analysis_id,
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
        analysis_id,
        resume.raw_text,
        url_hash,
        depends_on=Dependency(jobs=[scrape_job], allow_failure=True)
        if scrape_job
        else None,
    )

    return {"status": "queued", "job_id": analysis_id}


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
async def stream_job_analysis(
    job_id: str,
    candidate: Candidate = Depends(get_authenticated_candidate),
):
    owner_id = settings.redis_conn.get(f"analysis:owner:{job_id}")
    if owner_id is None or owner_id.decode() != str(candidate.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )

    return StreamingResponse(
        analysis_generator(job_id=job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

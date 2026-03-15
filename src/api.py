import json
import uuid

from datetime import datetime
from dataclasses import dataclass

import aiofiles
import pymupdf

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from psycopg import sql
from psycopg.rows import class_row
from rq.exceptions import NoSuchJobError
from rq.job import Job

from .deps import (
    get_resume_upload_dir,
    get_db_connection,
    get_scraper_registry,
    verify_content_hash_header,
)
from .logger import REQUEST_ID_CTX, logger
from .jobs import (
    ingress_llm,
    process_and_save_resume,
    scrape_job_details,
    upload_resume_to_s3,
)
from .models import Resume
from .settings import settings
from .redis import async_redis
from .text_processor import TextPreprocessor
from .utils import hash_url


router = APIRouter(prefix="")


VALID_FILE_FORMATS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
CHUNK_SIZE = 1024 * 1024  # 1MB


@router.post("/resumes/upload")
async def upload_resume(
    file: UploadFile,
    content_hash: str = Depends(verify_content_hash_header),
    resume_upload_dir=Depends(get_resume_upload_dir),
    db_conn=Depends(get_db_connection),
):
    if not file.filename or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename is required",
        )

    if file.content_type not in VALID_FILE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid file format. Only PDF and DOCX are allowed.",
        )

    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File size exceeds the maximum limit of 2MB.",
        )
    
    content_buffer = await file.read()
    
    with pymupdf.open(stream=content_buffer) as doc:
        text = chr(12).join([page.get_text() for page in doc])  # type: ignore

    raw_text = (
        TextPreprocessor(text)
            .remove_extra_whitespace()
            .normalize_unicode()
            .remove_boilerplates()
            .redact_pii()
            .get_text()
    )

    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File is empty.",
        )

    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stem, sep, ext = file.filename.rpartition(".")
    timestamped_name = f"{stem}-{ts}{sep}{ext}"

    destination_path = resume_upload_dir / timestamped_name

    async with aiofiles.open(destination_path, "wb") as out_file:
        await out_file.write(content_buffer)

    resume = Resume(
        filename=timestamped_name,
        raw_text=raw_text,
    )

    async with db_conn.cursor() as cur:
        await cur.execute(
            sql.SQL(
                """
                    INSERT INTO ria.resumes (
                        id,
                        filename,
                        raw_text,
                        content_hash,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (content_hash)
                    DO NOTHING
                    RETURNING id;
                """
            ),
            (
                resume.id,
                resume.filename,
                resume.raw_text,
                content_hash,
            ),
        )

        row = await cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has been previously uploaded, skipping processing",
        )
    
    logger.info(f"[POST: /resumes/upload]: Resume dispatched for LLM extraction", extra={
        "resume_id": resume.id,
    })
    process_and_save_resume.delay(REQUEST_ID_CTX.get(), resume.id)  # type: ignore
    logger.info(f"[POST: /resumes/upload]: Resume dispatched for S3 uploads", extra={
        "resume_id": resume.id,
    })
    upload_resume_to_s3.delay(REQUEST_ID_CTX.get(), resume.id, destination_path,)  # type: ignore

    return {"message": "Resume uploaded and processing initiated", "resume_id": str(resume.id)}


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

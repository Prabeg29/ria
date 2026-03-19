import json
import random
import uuid

from pathlib import Path

import boto3

from fastapi import status
from google import genai
from google.genai.errors import ClientError, ServerError
from playwright.async_api import async_playwright
from psycopg.rows import class_row
from psycopg.types.json import Json
from rq import Retry
from rq.decorators import job
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from .database import db_conn
from .logger import REQUEST_ID_CTX, logger
from .job_scraper import JobScraper
from .models import Resume, ScrapedJob
from .prompts import (
    ANALYZE_RESUME_AGAINST_JOB_PROMPT,
    EXTRACT_RESUME_PROMPT,
)
from .redis import publish
from .settings import settings

gemini_client = genai.Client(api_key=settings.gemini_api_key)

def retry_with_exponential_backoff(
    retry: int,
    initial: float = 1,
    max_value: float = 300,
    exp_base: float = 2,
    jitter: float = 1

) -> Retry:
    intervals = []
    for attempt in range(retry):
        jitter = random.uniform(0, jitter)
        try:
            exp = exp_base ** attempt
            result = initial * exp + jitter
        except OverflowError:
            result = max_value
        intervals.append(max(0, min(result, max_value)))
    return Retry(retry, intervals)


def handle_retry(job, connection, type, value, traceback):
    pass


@job(
    "llm",
    connection=settings.redis_conn,
    retry=retry_with_exponential_backoff(3),
    on_failure=handle_retry
)
async def process_and_save_resume(request_id: str, resume_id: uuid.UUID) -> None:
    REQUEST_ID_CTX.set(request_id)
    async with db_conn() as aconn:
        async with aconn.cursor(row_factory=class_row(Resume)) as cur:
            await cur.execute("""
                SELECT
                    resumes.id,
                    resumes.raw_text,
                    resumes.parsed_data
                FROM resumes
                WHERE resumes.id = %s
            """,
                (resume_id,),
            )
            resume = await cur.fetchone()

    if resume is None:
        logger.error(f"No resume found", extra={"resume_id": resume_id})
        return

    if resume.parsed_data:
        logger.info("Resume already parsed, skipping llm ingress", extra={
            "resume_id": resume_id,
        })
        return

    logger.info(f"Extracting content in json...", extra={
        "resume_id": resume_id
    })
    response = gemini_client.models.generate_content(
        model=settings.gemini_model,
        contents=EXTRACT_RESUME_PROMPT.format(text=resume.raw_text),
    )

    if response.text is None:
        logger.error(f"Error processing resume", extra={"resume_id": resume_id})
        return

    clean = response.text.strip().strip("`").replace("```json", "").replace("```", "")

    parsed_data = json.loads(clean)
    
    async with db_conn() as aconn:
        await aconn.execute("""
                UPDATE resumes
                SET parsed_data = %s,
                updated_at = NOW()
                WHERE id = %s
            """,
            (Json(parsed_data), resume.id,)
        )
        await aconn.commit()

    logger.info(f"Updated resume with parsed data", extra={
        "resume_id": resume_id,
    })
 

s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key,
        aws_secret_access_key=settings.aws_secret_key,
        region_name=settings.aws_region,
    )


@job("default", connection=settings.redis_conn)
async def upload_resume_to_s3(request_id:str, resume_id: uuid.UUID, file_path: Path) -> None:
    REQUEST_ID_CTX.set(request_id)
    logger.info("Starting S3 upload", extra={
        "filename": file_path.name,
        "resume_id": resume_id,
    })
    try:
        s3_object_name = f"{resume_id}_{file_path.name}"
        s3_client.upload_file(
            str(file_path),
            settings.aws_bucket,
            s3_object_name,
        )
        s3_url = f"https://{settings.aws_bucket}.s3.{settings.aws_region}.amazonaws.com/{s3_object_name}"

        logger.info("Uploaded to S3", extra={
            "filename": file_path.name,
            "resume_id": resume_id,
        })

        async with db_conn() as aconn:
            await aconn.execute("""
                    UPDATE resumes
                    SET s3_url = %s,
                    updated_at = NOW()
                    WHERE id = %s
                """,
                (Json(s3_url), resume_id,)
            )
            await aconn.commit()

            
        file_path.unlink()
        logger.info("[S3 Resume Upload]: Deleted local file after S3 upload", extra={
            "file_path": file_path
        })
    except Exception as e:
        logger.error("[S3 Resume Upload]: Failed to upload resume to S3", e)


@job(
    queue="default",
    connection=settings.redis_conn,
    retry=Retry(max=3, interval=[1, 30, 60]),
)
async def scrape_job_details(
    request_id: str,
    job_scraper: JobScraper,
    normalized_url: str,
    url_hash: str
) -> None:
    REQUEST_ID_CTX.set(request_id)

    await publish(request_id, "status", {
        "status": "scraping",
        "message": "Accessing job url..."
    })

    async with db_conn() as aconn:
        await aconn.execute(
            query="""
                UPDATE ria.scraped_jobs
                SET status = 'scraping',
                    updated_at = NOW()
                WHERE url_hash = %s;
            """,
            params=(url_hash,)
        )

    async with async_playwright() as p:
        browser = await p.firefox.connect(
            ws_endpoint=settings.browerless_ws,
        )
        try:
            page = await browser.new_page()
        
            await page.route("**/*.{png,jpg,jpeg,gif,css,woff2}", lambda route: route.abort())
            resp = await page.goto(
                url=normalized_url,
                wait_until="domcontentloaded",
            )
            
            if (
                resp and 
                resp.status == status.HTTP_404_NOT_FOUND
            ):
                async with db_conn() as aconn:
                    await aconn.execute(
                        query="""
                            UPDATE ria.scraped_jobs
                            SET status = 'scraped',
                                is_archived = true,
                                last_scraped_at = NOW(),
                                updated_at = NOW()
                            WHERE url_hash = %s;
                        """,
                        params=(url_hash,)
                    )
                await publish(request_id, "status", {
                    "status": "scraping",
                    "message": "Job not found"
                })

                return
            
            job_data = await job_scraper.extract(page)
            
            async with db_conn() as aconn:
                await aconn.execute(
                    query="""
                        UPDATE ria.scraped_jobs
                        SET scraped_data = %s,
                            status = 'scraped',
                            last_scraped_at = NOW(),
                            updated_at = NOW()
                        WHERE url_hash = %s;
                    """,
                    params=(Json(job_data), url_hash,)
                )
        except Exception:
            logger.info(
                "Scraping job details failed",
                exc_info=True,
                extra={
                    "normalized_job_url": normalized_url,
                    "url_hash": url_hash,
                }
            )
            async with db_conn() as aconn:
                await aconn.execute(
                    query="""
                        UPDATE ria.scraped_jobs
                        SET status = 'failed',
                            last_scraped_at = NOW(),
                            updated_at = NOW()
                        WHERE url_hash = %s;
                    """,
                    params=(url_hash,)
                )
            raise
        finally:
            await browser.close()


def is_retryable_error(e: Exception) -> bool:
    if isinstance(e, ServerError):
        return True
    
    if isinstance(e, ClientError):
        if e.code == 429:
            return True
    return False


@retry(
    retry=retry_if_result(is_retryable_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    before_sleep=before_sleep_log(logger, 40)
)
async def ingest_llm(resume_text: str, job_data):
    return await gemini_client.aio.models.generate_content_stream(
        model=settings.gemini_model,
        contents=ANALYZE_RESUME_AGAINST_JOB_PROMPT.format(
            resume_raw_text=resume_text,
            job=job_data
        )
    )


@job(
    queue="default",
    connection=settings.redis_conn,
    retry=Retry(max=3, interval=[1, 30, 60]),
)
async def ingress_llm(
    request_id: str,
    resume_text: str,
    url_hash: str
):
    REQUEST_ID_CTX.set(request_id)

    logger.info(
        "[Ingress LLM] Processing",
        extra={
            "url_hash": url_hash,
        }
    )

    await publish(request_id, "status", {
        "status": "analyzing",
        "message": "Reasoning with AI"
    })

    try:
        async with db_conn() as aconn:
            async with aconn.cursor(row_factory=class_row(ScrapedJob)) as cur:
                await cur.execute("""
                    SELECT
                        scraped_jobs.id,
                        scraped_jobs.status,
                        scraped_jobs.scraped_data,
                        scraped_jobs.last_scraped_at,
                        scraped_jobs.is_archived
                    FROM scraped_jobs
                    WHERE scraped_jobs.url_hash = %s
                    AND scraped_jobs.status = 'scraped'
                    AND scraped_jobs.is_archived = false
                    AND scraped_jobs.last_scraped_at > NOW() - INTERVAL '24 hours'
                """,
                    (url_hash,),
                )
                scraped_job = await cur.fetchone()
        
        if scraped_job is None:
            logger.info(
                "[Ingress LLM] No job found",
                extra={
                    "url_hash": url_hash,
                }
            )
            await publish(request_id, "done", {"status": "complete"}) 
            return
            

        response_stream = await ingest_llm(
            resume_text=resume_text,
            job_data=scraped_job.scraped_data
        )
            
        async for chunk in response_stream:
            if chunk.text:
                await publish(request_id, "delta", {"text": chunk.text})

        await publish(request_id, "done", {"status": "complete"}) 
    except Exception:
        logger.error("[Ingress LLM]: Job failed", exc_info=True, extra={
            "url_hash": url_hash
        })
        await publish(request_id, "done", {"status": "failed"}) 

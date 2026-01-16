import json
import uuid

from pathlib import Path

import boto3

from google import genai
from google.genai.errors import ClientError, ServerError
from playwright.async_api import (
    TimeoutError,
    async_playwright,
)
from psycopg.rows import class_row
from psycopg.types.json import Json
from rq.decorators import job
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from .database import db_conn
from .logger import REQUEST_ID_CTX, logger
from .job_scraper import JobScraper
from .models import Resume
from .prompts import (
    ANALYZE_RESUME_AGAINST_JOB_PROMPT,
    EXTRACT_RESUME_PROMPT,
)
from .redis import publish, redis
from .settings import settings

gemini_client = genai.Client(api_key=settings.gemini_api_key)


@job("default", connection=redis)
async def process_and_save_resume(request_id: str, resume_id: uuid.UUID) -> None:
    REQUEST_ID_CTX.set(request_id)
    try:
        async with db_conn() as aconn:
            async with aconn.cursor(row_factory=class_row(Resume)) as cur:
                await cur.execute("""
                    SELECT
                        resumes.id,
                        resumes.filename,
                        resumes.raw_text,
                        resumes.parsed_data,
                        resumes.updated_at
                    FROM resumes
                    WHERE resumes.id = %s
                """,
                    (resume_id,),
                )
                resume = await cur.fetchone()

        if resume is None:
            raise Exception(f"No resume found with ID {resume_id}.")

        logger.info(f"Starting resume processing for {resume.filename} with ID {resume_id}.")
        response = gemini_client.models.generate_content(
            model=settings.gemini_model,
            contents=EXTRACT_RESUME_PROMPT.format(text=resume.raw_text),
        )

        if response.text is None:
            raise Exception(f"No response found for resume with ID {resume_id}.")

        logger.info(f"Received response from Gemini", extra={
            "resume_id": resume_id,
            "resume_filename": resume.filename,
        })

        clean = response.text.strip().strip("`").replace("```json", "").replace("```", "")

        parsed_data = json.loads(json.dumps(clean))
        
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
            "resume_filename": resume.filename,
        })
    except Exception as e:
        logger.error(f"Error processing resume with (ID: {resume_id}): {e}")
    

s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key,
        aws_secret_access_key=settings.aws_secret_key,
        region_name=settings.aws_region,
    )


@job("default", connection=redis)
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


@retry(
    before_sleep=before_sleep_log(logger, 40),
    retry=retry_if_exception_type((TimeoutError,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def scrape_job(job_url: str, job_scraper: JobScraper):
    async with async_playwright() as p:
        browser = await p.firefox.connect(
            ws_endpoint="ws://browserless:3000/firefox/playwright?headless=false"
        )
        try:
            page = await browser.new_page()
        
            await page.route("**/*.{png,jpg,jpeg,gif,css,woff2}", lambda route: route.abort())
            await page.goto(
                url=job_url,
                wait_until="domcontentloaded",
            )
            return await job_scraper.extract(page)
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


@job("default", connection=redis)
async def scrape_job_and_ingress_llm(
    *,
    request_id: str,
    resume_text: str,
    job_url: str,
    job_scraper: JobScraper,
) -> None:
    REQUEST_ID_CTX.set(request_id)

    logger.info("[Scrape job and ingest llm]: Scraping job details", extra={
        "job_url": job_url
    })
    await publish(request_id, "status", {
        "status": "scraping",
        "message": "Accessing job url..."
    })

    job_data = await scrape_job(job_url=job_url, job_scraper=job_scraper)

    logger.info("[Scrape job and ingest llm]: Changing job details", extra={
        "job_url": job_url
    })
    await publish(request_id, "status", {
        "status": "analyzing",
        "message": "Reasoning with AI"
    })

    response_stream = await ingest_llm(
        resume_text=resume_text,
        job_data=job_data
    )
    
    async for chunk in response_stream:
        if chunk.text:
            await publish(request_id, "delta", {"text": chunk.text})

    await publish(request_id, "done", {"status": "complete"}) 

import json
import uuid

from datetime import datetime
from pathlib import Path

import aiofiles
import boto3
import pymupdf

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from google import genai
from psycopg import sql
from psycopg.rows import class_row
from psycopg.types.json import Json
from redis import Redis
from rq.decorators import job

from .database import db
from .deps import get_resume_upload_dir, get_db_connection
from .models import Resume
from .prompts import EXTRACT_RESUME_PROMPT
from .settings import settings
from .text_processor import TextPreprocessor


gemini_client = genai.Client(api_key=settings.gemini_api_key)


@job("default", connection=Redis(host=settings.redis_host))
async def process_and_save_resume(resume_id: uuid.UUID) -> None:
    await db.open_pool()
    try:
        async with db.connection() as aconn:
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

        print(f"Starting resume processing for {resume.filename} with ID {resume_id}.")
        response = gemini_client.models.generate_content(
            model=settings.gemini_model,
            contents=EXTRACT_RESUME_PROMPT.format(text=resume.raw_text),
        )

        if response.text is None:
            raise Exception(f"No response found for resume with ID {resume_id}.")

        clean = response.text.strip().strip("`").replace("```json", "").replace("```", "")

        parsed_data = json.loads(json.dumps(clean))
        
        async with db.connection() as aconn:
            await aconn.execute("""
                    UPDATE resumes
                    SET parsed_data = %s,
                    updated_at = NOW()
                    WHERE id = %s
                """,
                (Json(parsed_data), resume.id,)
            )
            await aconn.commit()

        print(f"Updated resume {resume.filename} (ID: {resume_id}) with parsed data.")
    except Exception as e:
        print(f"Error processing resume with (ID: {resume_id}): {e}")
    finally:
        await db.close_pool()
    

s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key,
        aws_secret_access_key=settings.aws_secret_key,
        region_name=settings.aws_region,
    )


@job("default", connection=Redis(host=settings.redis_host))
async def upload_resume_to_s3(resume_id: uuid.UUID, file_path: Path) -> None:
    print(f"Starting S3 upload for {file_path.name} with ID {resume_id}.")
    await db.open_pool()
    try:
        s3_object_name = f"{resume_id}_{file_path.name}"
        s3_client.upload_file(
            str(file_path),
            settings.aws_bucket,
            s3_object_name,
        )
        s3_url = f"https://{settings.aws_bucket}.s3.{settings.aws_region}.amazonaws.com/{s3_object_name}"

        async with db.connection() as aconn:
            await aconn.execute("""
                    UPDATE resumes
                    SET s3_url = %s,
                    updated_at = NOW()
                    WHERE id = %s
                """,
                (Json(s3_url), resume_id,)
            )
            await aconn.commit()

        print(f"[S3] Uploaded {file_path.name} (ID: {resume_id}) to {s3_url}")
            
        file_path.unlink()
        print(f"[S3] Deleted local file after S3 upload: {file_path}")
    except Exception as e:
        print(f"[S3] Failed to upload {file_path.name} (ID: {resume_id}) to S3: {e}")
    finally:
        await db.close_pool()


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
    resume_upload_dir=Depends(get_resume_upload_dir),
    db_conn=Depends(get_db_connection),
):
    if not file.filename or not file.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File is empty.",
        )

    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stem, sep, ext = file.filename.rpartition(".")
    timestamped_name = f"{stem}-{ts}{sep}{ext}"

    destination_path = resume_upload_dir / timestamped_name

    async with aiofiles.open(destination_path, "wb") as out_file:
        while content := await file.read(CHUNK_SIZE):
            await out_file.write(content)

    resume = Resume(
        filename=file.filename,
        raw_text=raw_text,
        parsed_data={},
        s3_url=None,
    )

    query = sql.SQL("""
            INSERT INTO ria.resumes (id, filename, raw_text, parsed_data, s3_url, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """
        )
    await db_conn.execute(
        query,
        (
            resume.id,
            resume.filename,
            resume.raw_text,
            json.dumps(resume.parsed_data),
            resume.s3_url,
        ),
    )

    process_and_save_resume.delay(resume.id)  # type: ignore
    upload_resume_to_s3.delay(resume.id, destination_path,)  # type: ignore

    return {"message": "Resume uploaded and processing initiated", "resume_id": str(resume.id)}

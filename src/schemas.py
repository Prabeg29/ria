from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


VALID_FILE_SIZES = {
    "min": 1024, # 1KB
    "max": 10 * 1024, # 10KB
}


class MimeType(str, Enum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ResumeUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    size: int = Field(ge=VALID_FILE_SIZES["min"], le=VALID_FILE_SIZES["max"],)
    content_type: MimeType


class ResumeUploadCompleteRequest(BaseModel):
    resume_id: UUID


class ResumeAnalyzeRequest(BaseModel):
    job_url: str

    @field_validator("job_url")
    @classmethod
    def job_url_must_have_registered_scraper(cls, v: str) -> str:
        from .job_scraper import ScraperRegistry

        ScraperRegistry.resolve(v)
        return v


class S3PresignedPost(BaseModel):
    url: str
    fields: dict[str, str]


class ResumeUploadInitResponse(BaseModel):
    id: UUID
    upload_url: S3PresignedPost

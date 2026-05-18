from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


VALID_FILE_SIZES = {
    "min": 50, # 50KB
    "max": 1024 * 1024, # 1MB
}


class MimeType(str, Enum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ResumeUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    size: int = Field(ge=VALID_FILE_SIZES["min"], le=VALID_FILE_SIZES["max"],)
    content_type: MimeType


class ResumeUploadCompletePayload(BaseModel):
    resume_id: UUID


@dataclass
class ResumeAnalyzeSchema:
    job_url: str


class S3PresignedPost(BaseModel):
    url: str
    fields: dict[str, str]


class ResumeUploadInitResponse(BaseModel):
    id: UUID
    upload_url: S3PresignedPost

from dataclasses import dataclass

from fastapi import HTTPException, status


VALID_FILE_FORMATS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB


@dataclass
class ResumeUploadSchema:
    filename: str
    size: int
    content_type: str

    def __post_init__(self):
        if not self.filename or not self.filename.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Filename is required",
            )
        if self.content_type not in VALID_FILE_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid file format. Only PDF and DOCX are allowed.",
            )
        if self.size and self.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds the maximum limit of 2MB.",
            )


@dataclass
class ResumeUploadCompleteSchema:
    resume_id: str


@dataclass
class ResumeAnalyzeSchema:
    job_url: str

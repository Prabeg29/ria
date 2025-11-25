from pathlib import Path

from fastapi import Request

from .database import db


def get_resume_upload_dir(request: Request) -> Path:
    return request.app.state.resume_upload_dir

async def get_db_connection():
    async with db.connection() as  conn:
        yield conn

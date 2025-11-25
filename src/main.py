from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, status

from .api import router
from .database import db, init_db
from .deps import get_db_connection
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    project_root = Path(__file__).resolve().parents[1]
    resume_upload_dir = project_root / "resumes"

    app.state.resume_upload_dir = resume_upload_dir
    await db.open_pool()
    await init_db()

    yield

    await db.close_pool()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.include_router(router=router)

@app.get("/health", status_code=status.HTTP_200_OK)
async def health(db_conn=Depends(get_db_connection)):
    try:
        await db_conn.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "resume_dir": str(app.state.resume_upload_dir.exists())
    }

import time
import uuid

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .database import init_db
from .deps import get_db_connection
from .job_scraper import ScraperRegistry, SeekJobScraper
from .logger import REQUEST_ID_CTX, logger
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    project_root = Path(__file__).resolve().parents[1]
    resume_upload_dir = project_root / "resumes"
    app.state.resume_upload_dir = resume_upload_dir

    logger.info("Initializing Database...")
    await init_db()
    logger.info("Database initialization completed")

    ScraperRegistry.register("www.seek.com.au", SeekJobScraper)
    app.state.scraper_registry = ScraperRegistry

    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = request.headers.get("X-REQUEST-ID") or str(uuid.uuid4())
    REQUEST_ID_CTX.set(req_id)

    start = time.perf_counter()

    response = await call_next(request)
    
    duration_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "HTTP Request",
        extra={
            "request_id": req_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
    )
    response.headers["X-REQUEST-ID"] = req_id
    return response
    
app.include_router(router=router)

@app.get("/health", status_code=status.HTTP_200_OK)
async def health(db_conn=Depends(get_db_connection)):
    await db_conn.execute("SELECT 1")
    db_status = "healthy"
    
    return {
        "status": "healthy",
        "database": db_status,
        "resume_dir": str(app.state.resume_upload_dir.exists())
    }

@app.get("/", status_code=status.HTTP_200_OK)
def root():
    return {
        "message": "Welcome to Resume Intelligence API",
        "docs": "Find docs at /docs",
        "health": "Check api health at /health",
    }

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, e: Exception):
    logger.critical("Unhandled exception", extra={
        "exception": e,
    })
    return JSONResponse(
        content={"message": "Something went wrong"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

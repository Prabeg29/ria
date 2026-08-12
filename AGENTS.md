# Repository Notes

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

This is a single-context repository; use the shared glossary and root ADR directory. See `docs/agents/domain.md`.

## Commands

- Use Python 3.13 and `uv`; install test dependencies with `uv sync --group dev`.
- `.env.example` uses Docker hostnames. For deterministic host-side tests, start dependencies with `DB_USERNAME=ria DB_PASSWORD=ria DB_DATABASE=ria docker compose -f dev.docker-compose.yml up -d db queue --wait`, then run `PYTHONDONTWRITEBYTECODE=1 DB_HOST=localhost DB_PORT=5430 DB_USERNAME=ria DB_PASSWORD=ria DB_DATABASE=ria DB_PGSCHEMA=ria REDIS_HOST=localhost AWS_DEFAULT_REGION=ap-southeast-2 uv run pytest tests/ -v`.
- Keep the explicit `tests/` path: bare `pytest` also traverses the persisted `db_data/` directory and can fail collection with `PermissionError`.
- Focus a test by keeping the same environment prefix and using a node ID, e.g. `PYTHONDONTWRITEBYTECODE=1 DB_HOST=localhost DB_PORT=5430 DB_USERNAME=ria DB_PASSWORD=ria DB_DATABASE=ria DB_PGSCHEMA=ria REDIS_HOST=localhost AWS_DEFAULT_REGION=ap-southeast-2 uv run pytest tests/api/test_stream.py::test_stream_response_content_type -v`.
- The only configured CI verification is pytest; there is no repository lint or typecheck configuration.

## Runtime Shape

- `src.main:app` is the FastAPI entrypoint. Its lifespan initializes `database/init.sql` and registers the Seek scraper; tests using `TestClient` therefore require PostgreSQL even when the test looks isolated.
- API handlers in `src/api.py` dispatch RQ jobs from `src/jobs.py` to three queues: `default` for PDF extraction, `scraping_queue` for Playwright, and `gemini_queue` for analysis. Matching workers are separate Compose services.
- Analysis output is a Redis stream keyed `analysis:stream:{request_id}`; the analyze response's `job_id` is that request ID, not an RQ job ID.
- Scraping currently supports only `seek.com.au`. `scrape_job_details` connects to a Playwright Browserless endpoint through `BROWSERLESS_WS`; Compose provides the local `browserless` service, while tests replace Playwright and the scraper registry with stubs.

## Tests And Data

- Tests use real PostgreSQL throughout and real Redis for SSE and `@pytest.mark.rate_limit` cases; S3 object access, Gemini, and Playwright calls are mocked. Rate limiting is automatically disabled for tests without that marker.
- `database/init.sql` is startup/bootstrap SQL, not a migration system. Its `CREATE ... IF NOT EXISTS` statements do not update tables already persisted under `db_data/`; schema changes need an explicit upgrade path or a deliberate local-volume rebuild.
- `adr/resume-upload-api.md` records the desired synchronous `POST /resumes` redesign, but current code still implements `/resumes/upload/init` -> direct S3 upload -> `/resumes/upload/complete` -> RQ extraction. Trust `src/api.py` and `database/init.sql` when describing current behavior.
- API-key authentication currently validates a key but resume records and resume queries are not tenant-scoped. Do not assume tenant isolation; the upload ADR documents this gap.

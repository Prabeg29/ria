# Resume Intelligence API

Reviewing a job posting that looks promising shouldn't mean opening a web chat, copying the job description, uploading your resume, and starting over for every new role. RIA handles this: paste a job posting URL, and it scrapes the posting, runs an LLM analysis against your resume, and streams the result back — no copy-paste, no repeated uploads, no manual tracking in a chat window.

## Features

- **Resume upload** via S3 presigned URL, with content-hash deduplication — the same file is processed exactly once regardless of how many times it is uploaded
- **Job posting scraping** from URL — extensible scraper architecture; currently supports seek.com.au, with planned support for Ashby, Greenhouse, Lever, Blackbird, and OIF
- **LLM-powered analysis** streamed in real time via SSE, comparing your resume against the scraped job posting
- **Per-tenant API key auth** and per-endpoint rate limiting

## Project Structure
```console
|--ria
|    |--.github
|    |    |--workflows
|    |    |   |--test.yml
|     
|    |--src
|    |   |--__init__.py
|    |   |--api.py
|    |   |--database.py
|    |   |--deps.py
|    |   |--job_scraper.py
|    |   |--jobs.py
|    |   |--logger.py
|    |   |--main.py
|    |   |--models.py
|    |   |--prompts.py
|    |   |--redis.py
|    |   |--schemas.py
|    |   |--settings.py
|    |   |--text_processor.py
|    |   |--utils.py
|    |   |--worker.py
|
|    |--tests
|
|    |--.dockerignore
|    |--.env
|    |--.env.example
|    |--.gitignore
|    |--dev.docker-compose.yml
|    |--Dockerfile
|    |--pyproject.toml
|    |--README.md
|    |--uv.lock
```

## Installation

### Prerequisites
* [Docker](https://www.docker.com/).
* [uv](https://docs.astral.sh/uv/) for Python package and environment management.

### Project Setup
1. Clone the repository
```sh
$ git clone git@github.com:Prabeg29/ria.git
```

2. Copy and set the environment variables
```sh
$ cd ria
$ cp .env.example .env
```

3. install all the dependencies with:
```sh
$ uv sync
```

4. Build docker image for dev stage
```sh
$ docker compose -f dev.docker-compose.yml build base --no-cache
```

5. Run all the sidecar services
```sh
$ docker compose -f dev.docker-compose.yml up
```
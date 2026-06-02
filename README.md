# Resume Intelligence API

## Features

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
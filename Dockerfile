# Stage: base
FROM python:3.13-slim AS base

ARG UID=1000
ARG GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid ${GID} ria && \
    useradd --uid ${UID} --gid ${GID}  --create-home --shell /bin/bash ria

WORKDIR /opt/app

# Stage: uv-base
FROM base AS uv-base

COPY pyproject.toml ./

RUN pip install --no-cache-dir uv

# Stage: dev
FROM uv-base AS dev

RUN chown -R ${UID}:${GID} /opt/app

USER ria

RUN uv sync

# Stage: export-deps
FROM uv-base AS export-deps

RUN uv export --format requirements.txt

# Stage: dependencies
FROM base AS dependencies

COPY --from=export-deps /opt/app/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Stage: runner
FROM base AS runner

COPY --from=dependencies /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin
COPY --chown=ria:ria . /opt/app/

USER ria

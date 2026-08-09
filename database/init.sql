CREATE SCHEMA IF NOT EXISTS ria;

SET search_path TO ria;

DO $$ BEGIN
    CREATE TYPE resume_processing_status AS ENUM('pending', 's3_uploaded', 'raw_extracted', 'llm_parsed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS ria.resumes(
    id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    content_hash CHAR(64) NOT NULL,
    filename VARCHAR(255) NOT NULL, 
    raw_text TEXT,
    parsed_data JSON,
    s3_key VARCHAR(255),
    last_upload_presigned_url_generated_at TIMESTAMP,
    processing_status resume_processing_status DEFAULT 'pending',
    processing_failure_remarks VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW () NOT NULL,
    CONSTRAINT pk_resumes PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_ria_resumes_id ON ria.resumes (id);

CREATE INDEX IF NOT EXISTS ix_ria_resumes_content_hash ON ria.resumes (content_hash);

DO $$ BEGIN
    CREATE TYPE scraping_status AS ENUM('queued', 'scraping', 'scraped', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS ria.scraped_jobs(
    id UUID NOT NULL,
    normalized_url TEXT NOT NULL,
    url_hash CHAR(64) UNIQUE NOT NULL,
    status scraping_status DEFAULT 'queued',
    scraped_data JSONB,
    last_scraped_at TIMESTAMP,
    is_archived BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW () NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ria_scraped_jobs_id ON ria.scraped_jobs (id);

CREATE INDEX IF NOT EXISTS ix_ria_scraped_jobs_url_hash ON ria.scraped_jobs (url_hash);

CREATE TABLE IF NOT EXISTS ria.tenants(
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW() 
);

CREATE TABLE IF NOT EXISTS ria.api_keys(
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants ON DELETE CASCADE,
    key_hash CHAR(64) UNIQUE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ria_api_keys_key_hash ON ria.api_keys(key_hash);

ALTER TABLE ria.resumes
ADD COLUMN IF NOT EXISTS candidate_id UUID;

ALTER TABLE ria.resumes
DROP CONSTRAINT IF EXISTS resumes_content_hash_key;

DO $$ BEGIN
    ALTER TABLE ria.resumes
    ADD CONSTRAINT fk_resumes_candidate
    FOREIGN KEY (candidate_id) REFERENCES ria.tenants(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE INDEX IF NOT EXISTS ix_ria_resumes_candidate_id
ON ria.resumes(candidate_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ria_resumes_candidate_content_hash
ON ria.resumes(candidate_id, content_hash);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ria_legacy_resumes_content_hash
ON ria.resumes(content_hash)
WHERE candidate_id IS NULL;

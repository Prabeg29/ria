CREATE TABLE IF NOT EXISTS ria.resumes(
    id UUID NOT NULL,
    filename VARCHAR(255) NOT NULL,
    raw_text TEXT,
    parsed_data JSON,
    s3_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW () NOT NULL,
    deleted_at TIMESTAMP,
    CONSTRAINT pk_resumes PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_ria_resumes_id ON ria.resumes (id);

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
    updated_at TIMESTAMP DEFAULT NOW () NOT NULL,
    deleted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ria_scraped_jobs_id ON ria.scraped_jobs (id);

CREATE INDEX IF NOT EXISTS ix_ria_scraped_jobs_url_hash ON ria.scraped_jobs (url_hash);

ALTER TABLE ria.resumes
ADD COLUMN IF NOT EXISTS content_hash CHAR(64) UNIQUE;

CREATE INDEX IF NOT EXISTS ix_ria_resumes_content_hash ON ria.resumes (content_hash);

ALTER TABLE ria.resumes
ADD COLUMN IF NOT EXISTS last_upload_presigned_url_generated_at TIMESTAMP;

DO $$ BEGIN
    CREATE TYPE resume_upload_status AS ENUM('pending', 'completed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

ALTER TABLE ria.resumes 
ADD COLUMN IF NOT EXISTS upload_status resume_upload_status DEFAULT 'pending';

# Resume Upload API

## Context

RIA's core resume requirement is straightforward: a user uploads a resume once and reuses it for multiple job analyses.

The current implementation uses a direct-to-S3 upload flow with two API endpoints, client-side content hashing, database state transitions, and asynchronous text extraction through Redis and RQ. This is a valid architecture for large files or high upload bandwidth, but resumes are currently limited to 1 MB.

The goal of this review is to determine which parts of the design solve current product or operational requirements and which parts add speculative complexity.

## Current Flow

```text
Client
  |
  | 1. Compute SHA-256
  | 2. POST /resumes/upload/init
  v
API -> PostgreSQL: create pending resume
API -> Client: return presigned S3 URL
  |
  | 3. Upload directly to S3
  | 4. POST /resumes/upload/complete
  v
API -> S3: verify object with HEAD
API -> PostgreSQL: pending -> s3_uploaded
API -> Redis/RQ: enqueue extraction
  |
  v
Worker -> S3: download document
Worker -> PyMuPDF: extract and preprocess text
Worker -> PostgreSQL: s3_uploaded -> raw_extracted
```

The public API currently consists of:

```text
POST /resumes/upload/init
POST /resumes/upload/complete
```

The first endpoint registers metadata and returns an S3 presigned URL. The second endpoint confirms that the client uploaded the object and dispatches text extraction.

## Why Each Component Exists

| Component | Current reason | Necessary now? |
|---|---|---|
| Client-side content hash | Deduplicate files before processing | Probably not |
| Presigned S3 upload | Keep file bytes away from the API server | Not for 1 MB files |
| Upload completion endpoint | Tell the API that the direct upload finished | Only required by presigned uploads |
| S3 `HEAD` request | Verify that the client completed the upload | Only required by presigned uploads |
| RQ extraction job | Move PDF processing outside the request | Probably not for text-only PDFs |
| Processing state machine | Coordinate the API, S3, and worker | Mostly caused by the architecture |
| PostgreSQL | Persist reusable resume text | Yes |
| Rate limiting | Protect storage and processing capacity | Yes |
| Authentication | Identify the caller | Yes |
| Tenant authorization | Ensure users can only access their own resumes | Yes, but currently incomplete |

## Findings

### Resumes Are Not Tenant-Owned

The API authenticates requests using tenant API keys, but the `resumes` table has no `tenant_id`. Upload completion and analysis retrieve resumes using only their UUID.

Consequences include:

- A caller with a valid API key can access another tenant's resume if its UUID is known.
- Content-hash deduplication operates globally across tenants.
- One user's upload can cause another user's identical file to be rejected.
- An unpredictable UUID reduces accidental access but is not an authorization mechanism.

Every resume must be associated with the authenticated tenant, and all resume queries must include that tenant relationship.

### The Content Hash Is Trusted Rather Than Verified

The client supplies `X-Content-Hash`, and the API stores it without calculating the hash of the uploaded object.

A client can therefore:

- Send a random hash for duplicate content.
- Reuse one hash for different files.
- Bypass deduplication.
- Interfere with globally deduplicated records.

The current design pays the complexity cost of content hashing without enforcing the corresponding integrity guarantee. If hashing is retained, the server must compute the hash from the actual file bytes.

### Queue Dispatch Can Race The Database Commit

The completion endpoint updates the resume to `s3_uploaded` and then enqueues the extraction job. The database transaction is committed when the request-scoped connection closes, which happens after the handler returns.

A worker can pick up the job before the transaction commits. It will still see the resume in `pending`, determine that the resume is ineligible for extraction, and exit successfully. The API returns `202 Accepted`, but no extraction is guaranteed to occur.

This is a database-and-queue dual-write problem. General solutions include:

- Commit the state change before enqueueing the job.
- Use a transactional outbox.
- Reconcile stalled records periodically.
- Avoid the queue when the work is small and bounded.

For the current upload constraints, avoiding the queue is the simplest solution.

### File Validation Is Inconsistent

The upload schema accepts PDF and DOCX, while the extraction worker always opens the object as a PDF.

Additional inconsistencies include:

- The configured minimum is 50 bytes, while documentation describes 50 KB.
- The request's declared `size` is validated but is not otherwise used.
- The S3 policy allows files as small as 50 bytes.
- The client-controlled `Content-Type` does not establish the actual file format.
- `X-Content-Hash` is not validated as a 64-character SHA-256 value.
- Filename length is unbounded even though database fields are limited to 255 characters.

The API should initially support PDF only and validate the document from its bytes rather than trusting its filename or media type.

### The State Machine Has Ambiguous Semantics

The current states are:

```text
pending -> s3_uploaded -> raw_extracted -> llm_parsed
       \                         /
        ----------> failed <----
```

Problems include:

- `pending` represents both a database record and an incomplete external upload.
- Completing an existing failed or fully processed resume returns `404`, even though the resource exists.
- Repeating completion for an `s3_uploaded` resume can enqueue duplicate jobs.
- A malformed document can exhaust retries while remaining `s3_uploaded`.
- `llm_parsed` belongs to functionality that is currently unused.
- There is no endpoint for clients to retrieve resume processing status.
- Clients discover readiness indirectly when an analysis succeeds or returns `404`.

These states mostly expose internal implementation details rather than useful resource behavior.

### Deduplication Does Not Directly Serve The Product Requirement

The product requires users to upload a resume once and reuse its ID. That does not require content-hash deduplication.

The current deduplication mechanism introduces:

- Client-side hashing.
- A custom request header.
- A unique database constraint.
- Conflict and retry-window handling.
- Presigned URL timestamps.
- Cross-tenant behavior.
- Additional upload states.

Users can avoid repeated uploads by retaining and reusing the returned `resume_id`. Deduplication should only remain if duplicate storage or processing is a demonstrated problem.

## Proposed Design

Replace the initialization and completion endpoints with one synchronous upload endpoint:

```http
POST /resumes
Content-Type: multipart/form-data
X-API-Key: <key>

file=<resume.pdf>
```

The server performs the complete workflow:

```text
Authenticate tenant
    |
Read at most 1 MB
    |
Verify PDF from its bytes
    |
Extract and preprocess text
    |
Reject empty or malformed documents
    |
Insert a ready resume owned by the tenant
    |
Return 201 Created
```

Example response:

```json
{
  "id": "75a07fa4-7ee0-4e45-a751-e5d58f72ea1b",
  "filename": "resume.pdf",
  "status": "ready"
}
```

Recommended responses:

| Condition | Response |
|---|---|
| Valid resume | `201 Created` |
| Missing file | `422 Unprocessable Content` |
| File over 1 MB | `413 Content Too Large` |
| Unsupported format | `415 Unsupported Media Type` |
| Corrupt or textless PDF | `422 Unprocessable Content` |
| Missing or invalid API key | `401 Unauthorized` or `403 Forbidden` |
| Upload rate exceeded | `429 Too Many Requests` |

## Why Synchronous Extraction Is Appropriate

The file is capped at 1 MB, and PyMuPDF extraction is local, bounded work. The upload flow does not call a slow external service.

Synchronous processing provides:

- One API call instead of three client operations.
- No client-side hashing requirement.
- No upload-completion protocol.
- No S3 verification request.
- No database-and-queue race.
- No upload-state orchestration.
- Immediate and specific validation errors.
- Simpler tests and observability.

The number of registered users is not the relevant scaling measurement. The relevant measurements are concurrent uploads, file size, extraction latency, memory usage, CPU usage, and API-server bandwidth.

## Original File Retention

The current product uses extracted resume text for analysis. If users do not need to download the original file and the system does not need to reprocess it, the original file should not be retained in S3.

Resumes contain sensitive personal information. Every retained copy introduces requirements around authorization, encryption, retention periods, deletion, and incident response.

S3 should remain in the upload workflow only when there is a concrete requirement such as:

- Users must be able to download their uploaded resume.
- Extraction algorithms will be rerun later.
- OCR or document conversion requires the original file.
- Legal or audit requirements require original-file retention.

If the original must be retained, the API can upload it to S3 internally during `POST /resumes`. Direct-to-S3 upload is still unnecessary at the current file-size limit.

## Proposed Data Model

Without original-file retention or asynchronous processing, the resume model can be reduced to:

```sql
CREATE TABLE resumes (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    filename VARCHAR(255) NOT NULL,
    raw_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Optional fields should only be added for established requirements:

| Field | Add when |
|---|---|
| `content_hash` | Per-tenant deduplication provides measurable value |
| `s3_key` | The original document must be retained |
| `status` | Resume processing must be asynchronous |
| `processing_failure_remarks` | Failed processing is persisted for later inspection or retry |

If deduplication is retained, uniqueness must be scoped to a tenant:

```sql
UNIQUE (tenant_id, content_hash)
```

The server must compute the content hash from the uploaded bytes.

## Scaling Triggers

Resume extraction should move back to a worker when measurements demonstrate one or more of the following:

- OCR or document conversion makes processing slow.
- Upload request latency becomes unacceptable.
- Extraction consumes enough CPU to affect normal API traffic.
- Supported files become materially larger.
- Processing needs independent retries.
- The deployment platform imposes restrictive request timeouts.

Presigned direct-to-S3 uploads should return when:

- File sizes become large.
- Concurrent upload bandwidth affects the API service.
- Clients require resumable or multipart uploads.
- Platform request-body limits become a problem.

These are measurable triggers. Complexity should be introduced in response to these conditions rather than anticipated user counts.

## Decision

Use one synchronous `POST /resumes` endpoint, support PDF only, extract text during the request, and associate every resume with the authenticated tenant.

Do not retain the original file in S3 unless original-file retention is an explicit product requirement. Do not retain content-hash deduplication unless duplicate uploads become a demonstrated problem.

Keep scraping and Gemini analysis asynchronous because they depend on slow and failure-prone external services. Their operational characteristics are different from local PDF text extraction and justify separate treatment.

## Subsequent Product Requirement

The job-search domain interview on 2026-08-09 established that RIA must retain
uploaded base resumes and generated resume artifacts. Original-file retention
is therefore now an explicit product requirement rather than a hypothetical
future need. The synchronous `POST /resumes` design remains applicable, but the
API must store the source file internally with tenant-scoped authorization and
must support an eventual candidate-driven retention and deletion policy.

# Auth and Rate Limit

## Problem Statement
With the API-first approach taken, we can observe that each API either directly calls a 3rd party service or the job
dispatched by the API calls 3rd party service when picked up by a worker. In absence of auth and rate limits, DDoS
attacks put toll on our system before even getting 429 HTTP errors from 3rd party services. APIs cannot be considered
production ready APIs if they do not have any auth and/or rate limits

## Approaches
### Auth
1. We can go with API keys
2. If and when we have a FE, consider issuing JWT tokens for user auth
3. Do not want to add your own user registration/login...? Go for OAuth2
    1. Google
    2. GitHub
    3. LinkedIn

### Rate Limiting

## Proposed Solution
With no frontend implemented yet, the simplest approach is issuing API keys. For now based on the request made via
email, create a tenant via a cli and issue an API key

### Database Table
```sql
CREATE TABLE IF NOT EXISTS ria.api_keys (
    id UUID NOT NULL,
    tenant_id UUID -- references id from tenants table
    key_hash CHAR(64) UNIQUE NOT NULL, -- Generate uuid and hash with sha-256
    last_used_at TIMESTAMP
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
); 
```
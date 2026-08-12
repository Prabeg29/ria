# 01 — Candidate Ownership Boundary

**What to build:** Ensure that one authenticated account resolves to exactly one Candidate and that the existing resume and analysis workflow is isolated by that ownership boundary. This is the expand step that makes later Candidate-owned workflows safe to add without exposing one Candidate's resources or work to another.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A valid API key supplies the authenticated Candidate ownership context to each protected operation rather than only reporting that authentication succeeded.
- [x] Existing resume upload initialization, upload completion, and resume analysis operations only read or mutate resources owned by the authenticated Candidate.
- [x] Existing background work receives enough ownership context to prevent processing another Candidate's resource.
- [x] Resume duplicate detection and uniqueness are scoped to the Candidate, so identical files owned by different Candidates do not conflict.
- [x] A Candidate using another Candidate's resource identifier receives a response that does not reveal whether that resource exists.
- [x] Invalid and missing API-key behavior remains unchanged.
- [x] Valid same-Candidate resume upload and analysis behavior remains unchanged.
- [ ] Existing persisted databases have an explicit, repeatable upgrade path for the ownership relationship and Candidate-scoped constraints.
- [ ] Reapplying the database upgrade is safe and does not duplicate or corrupt ownership data.
- [x] HTTP acceptance tests use at least two authenticated Candidates and prove isolation for reads, mutations, duplicate detection, and dispatched work.
- [x] Existing pytest verification remains green.

## Comments

The explicit legacy-data upgrade and idempotency criteria are deferred until the agreed SQLAlchemy and Alembic adoption. Fresh schemas require Candidate ownership, while existing nullable rows remain isolated and retain legacy hash uniqueness until that migration is implemented.

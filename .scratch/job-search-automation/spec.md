# Automate Candidate-Owned Job Search, Shortlisting, Tailoring, and Outcome Tracking

Status: ready-for-agent

## Problem Statement

RIA currently provides a FastAPI backend for uploading a resume, submitting a single job URL, scraping that posting, and streaming a one-off LLM analysis. The implementation uses raw psycopg queries and bootstrap SQL, Redis/RQ workers, S3-backed resume storage, Playwright scraping, and Gemini analysis. Only Seek job URLs are currently supported.

This implementation does not yet provide the candidate-owned, repeatable job-search workflow required by the product:

- Authentication validates an API key but does not return a tenant identity to handlers.
- Resumes, scraped jobs, analyses, and queries are not scoped to the authenticated tenant.
- A Base Resume is treated as analysis text rather than an input to a candidate-approved Verified Profile.
- There are no Search Campaigns, Approved Source Queries, Search Runs, canonical Job Opportunities, versioned job descriptions, Eligibility decisions, reproducible Fit Assessments, Preference Scores, or Daily Shortlists.
- Current analysis is an LLM-generated stream rather than an application-owned scoring rubric.
- Duplicate handling is URL-based and does not distinguish Source Listings from canonical Job Opportunities.
- There is no tailoring, Draft Revision, rendering, Application Candidacy, submission confirmation, Application Event timeline, or outcome analytics.
- There is no frontend, despite the target workflow requiring candidates to review and action work in the RIA web application.
- PostgreSQL is initialized through idempotent bootstrap SQL rather than a migration system, so bootstrap changes do not upgrade existing persisted databases.

RIA needs to evolve from one-off resume analysis into a daily job-search workflow that improves a Candidate’s chance of reaching an initial recruiter conversation without fabricating experience or submitting applications without explicit Candidate approval.

## Solution

Implement the complete candidate-owned job-search domain:

- Map each authenticated account to exactly one Candidate and scope every read, mutation, job, and artifact to that ownership boundary.
- Retain uploaded Base Resumes and use them to extract Proposed Profile Facts that become usable only after individual Candidate approval.
- Maintain an immutable, versioned Verified Profile as the canonical source for assessment and tailoring.
- Allow multiple independently configured Search Campaigns with Candidate-approved source queries.
- Run scheduled discovery across Seek and public Greenhouse, Ashby, and Lever boards while retaining source provenance.
- Resolve Source Listings into canonical Job Opportunities without automatically merging records based only on semantic similarity.
- Evaluate work-authorization Eligibility before applying an application-owned Fit Score rubric.
- Calculate Preference Score separately from Fit Score.
- Generate one immutable Candidate-wide Daily Shortlist containing zero through five newly presented Qualified Opportunities.
- Allow the Candidate to accept or dismiss shortlist items through the RIA web application.
- Start an Application Candidacy only after acceptance and generate an editable Markdown Tailored Resume Draft using verified facts only.
- Save immutable Draft Revisions and render a selected revision to ATS-friendly DOCX or PDF on demand.
- Retain Base Resumes, Draft Revisions, and rendered artifacts until Candidate deletion or account deletion.
- Require explicit Candidate confirmation before recording submission.
- Track post-submission progress through append-only Application Events and derive Current Application Stage as a projection.
- Provide outcome analytics by campaign, source, and score band without automatically changing scoring rules or campaign preferences.

## User Stories

1. As an authenticated account holder, I want exactly one Candidate identity so that all job-search activity has an unambiguous owner.
2. As a Candidate, I want every profile, campaign, shortlist, candidacy, event, and artifact scoped to my account so that another account cannot read or mutate it.
3. As a Candidate, I want to upload a PDF Base Resume through one synchronous request so that validation and text extraction complete without a separate upload-completion protocol.
4. As a Candidate, I want my uploaded Base Resume retained so that it remains available as an input artifact under my retention controls.
5. As a Candidate, I want my Base Resume treated as an input rather than an authoritative source so that extracted claims cannot silently become facts.
6. As a Candidate, I want structured claims extracted from a Base Resume as Proposed Profile Facts so that I can review them before use.
7. As a Candidate, I want to edit a Proposed Profile Fact before approval so that the resulting fact accurately reflects my experience.
8. As a Candidate, I want to approve Proposed Profile Facts individually so that only explicitly verified claims become Verified Profile Facts.
9. As a Candidate, I want to reject or remove a Proposed Profile Fact so that unsupported claims do not enter my Verified Profile.
10. As a Candidate, I want unapproved content excluded from Fit Assessments and Tailored Resume Drafts so that RIA never relies on unverified claims.
11. As a Candidate, I want each approval, edit, or removal to create an immutable Profile Version so that historical work remains reproducible.
12. As a Candidate, I want each Fit Assessment and tailored artifact to reference the Profile Version that produced it so that later profile changes do not rewrite history.
13. As a Candidate, I want the newest approved Profile Version used for future work so that new assessments reflect my current verified facts.
14. As a Candidate, I want a new Profile Version to trigger reassessment of unactioned opportunities and unsubmitted Application Candidacies so that current work reflects newly verified evidence.
15. As a Candidate, I want existing assessments and Draft Revisions retained after a profile change so that prior decisions remain auditable.
16. As a Candidate, I want affected current drafts marked stale after a profile change so that I know they were generated from an older Profile Version.
17. As a Candidate, I want to regenerate a stale draft or explicitly keep it so that I retain control over application material.
18. As a Candidate, I want multiple active Search Campaigns so that I can pursue independently configured job-search targets.
19. As a Candidate, I want each Search Campaign to define target roles, locations, work modes, seniority, compensation preferences, sources, schedule participation, maximum job age, and campaign priority so that searches reflect distinct goals.
20. As a Candidate, I want RIA to generate source-specific queries from structured campaign targets so that discovery can use each Source effectively.
21. As a Candidate, I want to preview and approve every source-specific query before activating a Search Campaign so that RIA searches only with my approval.
22. As a Candidate, I want each Search Run associated with its Search Campaign so that discovered results have reproducible campaign provenance.
23. As a Candidate, I want the first usable discovery release to support Seek and public Greenhouse, Ashby, and Lever boards so that the initial workflow spans the approved Sources.
24. As a Candidate, I want discovered Source Listings to retain their Source, source identity, URL, application URL, and provenance so that I can understand where each listing came from.
25. As a Candidate, I want discovery integrations to comply with each Source’s access and usage constraints so that discovery does not depend on inappropriate access.
26. As a Candidate, I want authenticated discovery, when supported, to run in a Candidate-controlled browser agent or extension so that reusable browser credentials are not transferred to RIA.
27. As a Candidate, I want RIA to receive discovered listing data rather than reusable browser session credentials so that authenticated discovery preserves my control.
28. As a Candidate, I want incomplete discoveries retained for later fetch retries so that a temporary lack of details does not permanently lose a potential opportunity.
29. As a Candidate, I want incomplete discoveries excluded from scoring and shortlisting so that decisions are not made from inadequate data.
30. As a Candidate, I want assessment to require an employer, title, viable application URL, verified open state, and enough description content to identify responsibilities and qualifications.
31. As a Candidate, I want multiple Source Listings for the same real-world opening represented by one canonical Job Opportunity so that duplicates do not fragment assessment.
32. As a Candidate, I want Source Listings automatically merged only when they share deterministic identity, such as an ATS requisition identifier, so that automatic deduplication is explainable.
33. As a Candidate, I want semantic employer-title-location matches presented as duplicate-resolution proposals so that I decide whether uncertain matches represent the same Job Opportunity.
34. As a Candidate, I want semantic similarity alone prevented from merging Source Listings so that distinct openings are not accidentally combined.
35. As a Candidate, I want a Job Opportunity to remain open while at least one verified Source Listing still accepts applications so that one closed listing does not hide an available opening.
36. As a Candidate, I want source closure and reopening to change availability without creating a new Job Opportunity so that its identity remains stable.
37. As a Candidate, I want job descriptions stored as immutable Job Description Versions so that assessments can be reproduced.
38. As a Candidate, I want changes to requirements, responsibilities, seniority, or scope to create a new Job Description Version and Fit Assessment so that material changes are reconsidered.
39. As a Candidate, I want employment terms and listing availability tracked separately from material description changes so that they do not incorrectly create description versions.
40. As a Candidate, I want identity-field changes routed to duplicate-resolution review rather than automatic reassessment so that possible identity changes receive explicit review.
41. As a Candidate, I want work authorization evaluated before scoring so that ineligible opportunities cannot qualify.
42. As a Candidate, I want an explicit conflict between a posting’s work-authorization requirement and my Verified Profile to produce failed Eligibility.
43. As a Candidate, I want omitted authorization requirements to produce Uncertain Eligibility when I am generally authorized in the jurisdiction so that potentially valid roles are not discarded.
44. As a Candidate, I want Uncertain Eligibility made visible in the shortlist so that I can investigate before applying.
45. As a Candidate, I want location, work mode, seniority, compensation, employer, and role preferences treated as suitability preferences rather than hard eligibility exclusions.
46. As a Candidate, I want every Fit Assessment to compare a specific Profile Version with a specific Job Description Version so that its result is reproducible.
47. As a Candidate, I want the Fit Score to range from 0 through 100 and measure verified support for job requirements and responsibilities rather than recruiter-call probability.
48. As a Candidate, I want to see requirement-level evidence supporting a Fit Assessment so that the Fit Score is explainable.
49. As a Candidate, I want the fixed rubric to allocate 40 points to required qualifications, 30 to comparable responsibility evidence, 15 to seniority and scope, 10 to preferred qualifications, and 5 to domain context.
50. As a Candidate, I want extracted items within a rubric dimension weighted equally by default so that the score is deterministic.
51. As a Candidate, I want an item’s weight increased only when employer text explicitly marks it as essential, core, or primary so that inferred importance does not distort scoring.
52. As a Candidate, I want direct verified evidence to receive `1.0` credit, explained transferable evidence to receive `0.5`, and unsupported requirements to receive `0`.
53. As a Candidate, I want adjacent or transferable experience identified as transferable rather than direct experience so that RIA does not misrepresent my background.
54. As a Candidate, I want a verified skill without linked work, project, or achievement context limited to `0.5` credit so that unsupported skill lists do not receive full evidence credit.
55. As a Candidate, I want full skill credit to require verified contextual evidence of using that skill.
56. As a Candidate, I want a genuine unsupported mandatory requirement to cap the Fit Score below 75 so that strength elsewhere cannot conceal a critical gap.
57. As a Candidate, I want an LLM limited to extraction, classification, and evidence mapping while application-owned policy computes the score so that scoring remains deterministic.
58. As a Candidate, I want a separate campaign-weighted Preference Score from 0 through 100 so that desirability does not alter qualification.
59. As a Candidate, I want location, work mode, compensation, and employer desirability excluded from the Fit Score so that preferences cannot qualify a weak match.
60. As a Candidate, I want unknown preference values excluded from the denominator and reflected as reduced confidence so that missing data is not treated as a match or mismatch.
61. As a Candidate, I want only eligible Job Opportunities with a Fit Score of at least 75 treated as Qualified Opportunities.
62. As a Candidate, I want all active Search Campaigns to compete for one Candidate-wide Daily Shortlist so that the best opportunities are selected across my searches.
63. As a Candidate, I want one Daily Shortlist generated per local calendar day at my configured local time and IANA time zone.
64. As a Candidate, I want each Daily Shortlist to contain no more than five newly presented Qualified Opportunities.
65. As a Candidate, I want the Daily Shortlist allowed to contain zero or one item when too few new opportunities qualify so that quality is not sacrificed to meet the target minimum of two.
66. As a Candidate, I want Qualified Opportunities ordered by descending Fit Score, then Preference Score, freshness, and campaign priority.
67. As a Candidate, I want campaigns to receive no reserved shortlist slots so that lower-quality results are not promoted solely for campaign representation.
68. As a Candidate, I want campaign-specific freshness rules applied before an opportunity is shortlisted.
69. As a Candidate, I want discovery time usable for freshness when a Source omits publication date, with that uncertainty shown to me.
70. As a Candidate, I want duplicate Source Listings for one unchanged Job Opportunity to consume at most one shortlist slot.
71. As a Candidate, I want an unchanged Job Opportunity prevented from appearing again in a later Daily Shortlist.
72. As a Candidate, I want an Unactioned Shortlist Item to remain actionable in its original digest until accepted, dismissed, or closed.
73. As a Candidate, I want the Daily Shortlist left unchanged after generation rather than refilled during the day.
74. As a Candidate, I want a materially changed Job Opportunity eligible to return only when it remains unactioned and qualified.
75. As a Candidate, I want accepted or dismissed Job Opportunities prevented from resurfacing automatically after a material change.
76. As a Candidate, I want to view Daily Shortlists and action their items in the RIA web application.
77. As a Candidate, I want each shortlisted item to display its source links, Fit Score, supporting evidence, preference information, freshness uncertainty, and Eligibility uncertainty where applicable.
78. As a Candidate, I want to dismiss a shortlisted Job Opportunity when I do not wish to pursue it.
79. As a Candidate, I want accepting a shortlisted Job Opportunity to create an Application Candidacy so that pursuit is tracked explicitly.
80. As a Candidate, I want acceptance kept distinct from submission so that choosing to investigate a role never claims I have applied.
81. As a Candidate, I want tailoring to begin only after I accept the shortlist item.
82. As a Candidate, I want each Tailored Resume Draft restricted to facts supported by its Profile Version so that no unsupported claim is introduced.
83. As a Candidate, I want tailoring allowed to select, reorder, and reword verified facts so that the resume can emphasize relevant experience without fabrication.
84. As a Candidate, I want canonical Tailored Resume Drafts stored as Markdown so that editable source content remains authoritative.
85. As a Candidate, I want to edit a Tailored Resume Draft directly so that I retain control over its wording.
86. As a Candidate, I want every draft save to create an immutable Draft Revision so that changes are preserved rather than overwritten.
87. As a Candidate, I want to select a Draft Revision for rendering so that I control which version is used.
88. As a Candidate, I want a selected Draft Revision rendered to ATS-friendly DOCX or PDF only when requested.
89. As a Candidate, I want rendering to leave the selected Markdown Draft Revision unchanged.
90. As a Candidate, I want every Rendered Resume to reference exactly one Draft Revision so that the authoritative source is always known.
91. As a Candidate, I want uploaded Base Resumes, Markdown Draft Revisions, and every rendered DOCX and PDF retained until I delete them or delete my account.
92. As a Candidate, I want to delete an individual retained artifact so that I control retained personal information.
93. As a Candidate, I want account deletion to remove all Candidate-owned domain data and retained artifacts.
94. As a Candidate, I want to abandon an unsubmitted Application Candidacy without falsely recording a submission.
95. As a Candidate, I want only my explicit confirmation to transition an Application Candidacy to Submitted Application.
96. As a Candidate, I want submission confirmation to record the selected Draft Revision, occurrence time, and application URL when known.
97. As a Candidate, I want application progress recorded as immutable Application Events so that history is not overwritten.
98. As a Candidate, I want to record `submitted`, `recruiter_response`, `interview`, `rejected`, `withdrawn`, and `offer` events.
99. As a Candidate, I want each Application Event to have an occurrence time and optional notes.
100. As a Candidate, I want repeated interview events allowed so that multiple interview rounds can be represented.
101. As a Candidate, I want a mistaken Application Event corrected with a Void Event containing a reason and optional replacement rather than deletion.
102. As a Candidate, I want voided events retained in history but excluded from Current Application Stage projections.
103. As a Candidate, I want Current Application Stage derived from Application Events rather than maintained as an independently authoritative mutable status.
104. As a Candidate, I want application outcomes summarized by Search Campaign, Source, and score band so that I can understand results.
105. As a Candidate, I want outcome analytics prevented from automatically changing Fit Score rules or Preference Score weights so that policy changes remain explicit.

## Implementation Decisions

- V1 maps one authenticated account to exactly one Candidate. All reads, mutations, background work, and retained artifacts must enforce that ownership boundary.
- The current API-key dependency must provide authenticated ownership context rather than merely validating a key and returning no tenant identity.
- The implementation starts from a FastAPI backend using raw psycopg access, PostgreSQL bootstrap SQL, Redis/RQ jobs, Playwright source access, object storage, and Gemini integration.
- The current database bootstrap is not a migration system. Changes to existing persisted tables require an explicit upgrade path or deliberate data-store rebuild; adding idempotent creation statements alone will not upgrade existing installations. The migration mechanism remains undecided.
- Replace the current direct-to-storage initialization and completion protocol with the previously decided synchronous PDF-only resume upload behavior. The API validates bytes, extracts text during the request, stores the Base Resume internally, and associates it with the authenticated owner.
- Original Base Resume retention is now an explicit requirement. Internal storage must enforce Candidate-scoped authorization and support Candidate-controlled artifact deletion and account deletion.
- Scraping and LLM work remain asynchronous because they depend on slow and failure-prone external services. Redis/RQ remains the current job execution mechanism.
- The Verified Profile, not a Base Resume, is the canonical Candidate source of truth. Only individually approved Verified Profile Facts can support assessment or tailoring.
- Profile Versions, Job Description Versions, Fit Assessments, Draft Revisions, Rendered Resumes, and Application Events preserve immutable historical references.
- Work authorization is the only V1 hard Eligibility rule and is evaluated before Fit Score calculation.
- The application computes Fit Score using the fixed 40/30/15/10/5 rubric and fixed evidence-credit policy. An LLM may extract and classify information but does not own the scoring result.
- Unsupported mandatory requirements cap Fit Score below the qualification threshold.
- Preference Score is campaign-weighted and independent of Fit Score. Unknown values are excluded from the denominator and reduce reported confidence.
- A Qualified Opportunity must be eligible and have a Fit Score of at least 75.
- Source Listings preserve provenance and resolve to canonical Job Opportunities. Only deterministic shared identity permits automatic merging; semantic similarity creates a Candidate-review proposal.
- Job Opportunity availability is derived from verified Source Listings. Material description changes produce immutable versions and reassessment, while employment terms, availability, and identity changes follow their separately defined treatment.
- Search Campaign activation requires Candidate approval of generated source-specific queries.
- One immutable Daily Shortlist is generated per Candidate local day, contains zero through five newly presented Qualified Opportunities, and is not refilled.
- Daily Shortlist ordering is Fit Score, Preference Score, freshness, then campaign priority, all descending where applicable. Campaigns have no reserved slots.
- The initial discovery release supports Seek and public Greenhouse, Ashby, and Lever boards.
- Every Source integration retains provenance and complies with applicable access constraints. Authenticated discovery does not transfer reusable browser credentials to RIA.
- Acceptance creates an Application Candidacy but never a submission.
- Markdown is the canonical Tailored Resume Draft representation. Each save creates an immutable Draft Revision, and requested DOCX or PDF files remain representations of one selected revision.
- All Base Resumes, Draft Revisions, and rendered artifacts are retained until individual artifact deletion or account deletion.
- Only explicit Candidate confirmation creates a Submitted Application and its submission event.
- Application Events are append-only. Corrections use Void Events, and Current Application Stage is a projection.
- The RIA web application is part of V1 because the Candidate must review and action Daily Shortlists, profile facts, drafts, submissions, and outcomes there. No frontend currently exists, and no frontend technology has been selected by the ADR.
- API resource shapes, endpoint names beyond the decided synchronous resume upload, detailed profile and campaign fields, projection precedence, and operational scheduling/retry policies are not prescribed by this specification.

## Testing Decisions

- Use HTTP workflow acceptance tests as the primary testing seam.
- Run acceptance tests against real PostgreSQL so ownership, versioning, immutability, uniqueness, relationships, projections, and transaction behavior are exercised.
- Use deterministic fake queue, Source, LLM, storage, renderer, and clock adapters in acceptance tests.
- Drive complete workflows through authenticated HTTP requests and assert both responses and persisted domain outcomes.
- Create at least two authenticated Candidates in ownership tests and verify every Candidate-owned resource is inaccessible and immutable across the ownership boundary.
- Cover Base Resume upload, Proposed Profile Fact review, Profile Version creation, campaign setup, query approval, activation, discovery, assessment, shortlist generation, shortlist action, tailoring, rendering, submission confirmation, event recording, voiding, analytics, artifact deletion, and account deletion.
- Exercise local-day and time-zone behavior with the fake clock, including one shortlist per local day, daylight-boundary behavior, and no same-day refill.
- Exercise queue dispatch and dependency behavior through the fake queue without running Redis or workers in primary workflow tests.
- Exercise Source success, incomplete discovery, closure, reopening, retries, material changes, duplicate identity, and semantic duplicate proposals through deterministic fake Source responses.
- Exercise requirement extraction and evidence mapping with deterministic fake LLM responses while asserting that application policy, not LLM output, computes Eligibility, Fit Score, qualification, ordering, and confidence.
- Exercise storage and renderer interactions through fakes while asserting retention, authorization, deletion, revision references, and that rendering does not mutate Markdown.
- Support the HTTP acceptance suite with pure domain policy tests for Eligibility, Fit Score dimensions, item weighting, evidence credit, mandatory-requirement caps, Preference Score confidence, qualification, shortlist ordering, freshness, resurfacing, profile staleness, and Current Application Stage projection.
- Support the suite with frozen-fixture Source adapter contract tests for Seek, Greenhouse, Ashby, and Lever. Fixtures must verify normalization, extraction, provenance, source identity, open state, publication-date uncertainty, required assessment data, and closure behavior without live network access.
- Follow existing API test patterns by using FastAPI’s test client, authenticated default headers, seeded PostgreSQL fixtures, explicit teardown, dependency overrides, and assertions against HTTP status and response content.
- Follow existing dispatch test patterns by replacing external job dispatch, asserting invocation and dependency relationships, and verifying that cached or in-flight source work is reused where applicable.
- Follow existing job test patterns by invoking asynchronous job functions directly, mocking Playwright, storage, and Gemini boundaries, and asserting persisted state transitions and published outcomes.
- Preserve coverage of invalid authentication, missing resources, invalid input, unsupported Sources, incomplete data, terminal states, external failures, retries, rate limiting, and idempotent/repeated requests.
- Preserve the existing pattern of testing rate limits with real Redis only where the rate limiter itself is under test.
- Preserve the existing SSE pattern only for any streaming behavior that remains: use real Redis, assert media type and event order, and ensure streams terminate on a final event.
- Ensure acceptance tests prove every domain invariant, including no unauthorized access, no use of unapproved facts, no fabricated tailored claims, no autonomous submission, no ineligible shortlist entry, no score-below-75 shortlist entry, no duplicate shortlist slot, no second daily shortlist, and no erased Application Event.

## Out of Scope

- Autonomous application submission.
- Email delivery of the Daily Shortlist.
- An API-only consumer workflow as a substitute for the RIA web application.
- Cover letters, screening-question answers, and recruiter outreach.
- Interview preparation, contact management, and follow-up automation.
- Treating Fit Score as a prediction of recruiter-call probability.
- Automatically changing Fit Score rules or Preference Score weights from application outcomes.
- Hard Eligibility exclusions other than work authorization in V1.
- Automatically merging Source Listings based only on semantic similarity.
- Treating a Base Resume or Rendered Resume as independently authoritative.
- VC aggregators, Boolean search, and authenticated LinkedIn discovery in the first usable discovery release.
- Reusable browser-session credential storage.
- A specific frontend framework.
- A specific database migration framework until that open implementation decision is resolved.

## Further Notes

- The originating domain ADR remains proposed and identifies unresolved details that must not be guessed during implementation.
- Exact structured fields and validation rules for Search Campaigns and profile facts remain open.
- Source-specific access constraints for the selected first-release Sources require confirmation.
- Current Application Stage precedence for terminal Application Events remains open.
- Operational scheduling, retry, reconciliation, and Source rate-limit policies remain open.
- The current code supports only Seek URL scraping and one-off analysis. References to Greenhouse, Ashby, Lever, campaigns, discovery, deterministic scoring, tailoring, rendering, tracking, and the web application describe target behavior, not existing functionality.
- Current authentication records a tenant relationship for API keys, but handlers do not receive that tenant identity and current resume and job queries are not tenant-scoped. Ownership enforcement is therefore foundational rather than an incremental authorization enhancement.
- Current schema initialization uses create-if-absent bootstrap behavior. Existing persisted databases will not acquire new columns, constraints, ownership relationships, or tables merely by restarting the application.
- Original-file retention supersedes the earlier suggestion that uploaded resumes need not be retained. Base Resumes and generated resume artifacts are now explicitly retained, with Candidate-scoped authorization and Candidate-controlled deletion required.

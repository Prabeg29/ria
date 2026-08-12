# Domain Glossary

This is the living ubiquitous-language glossary for RIA's job search domain.

| Term | Meaning |
|---|---|
| Candidate | The person whose profile is evaluated and whose approval is required to submit an application. |
| Verified Profile | The canonical, candidate-approved set of factual experience, skills, achievements, education, work authorization, and preferences. |
| Proposed Profile Fact | A structured claim extracted from a resume or entered by the candidate that cannot be used until the candidate approves it. |
| Verified Profile Fact | An individually candidate-approved factual claim that may support assessments and tailored artifacts. |
| Profile Version | An immutable revision of the Verified Profile used to reproduce an assessment or tailored artifact. |
| Base Resume | A candidate-provided document used to seed or present profile facts; it is not independently authoritative. |
| Search Campaign | An independently configured job-search target with its own roles, preferences, sources, and freshness policy. A candidate may have multiple active campaigns. |
| Approved Source Query | A source-specific query generated from structured campaign targets and approved by the candidate before campaign activation. |
| Search Run | One execution of a Search Campaign that discovers and processes listings. |
| Source | A platform, job board, ATS, search engine, VC job board, or public careers site from which listings are discovered. |
| Source Listing | A source-specific representation of a job, including its URL and provenance. Multiple Source Listings can refer to one Job Opportunity. |
| Job Opportunity | The canonical real-world opening being considered, independent of where it was listed. |
| Job Description Version | An immutable snapshot of requirements and responsibilities used for reproducible assessment. Material description changes create a new version. |
| Eligibility | A pass, fail, or uncertain determination made before scoring. Work authorization is currently the only hard eligibility rule. |
| Uncertain Eligibility | A non-failing work-authorization result used when the candidate is generally authorized for the jurisdiction but the posting omits definitive requirements. It must be visible in the shortlist. |
| Fit Assessment | A versioned comparison of a Job Opportunity with a Profile Version, including requirement-level evidence and a Fit Score. |
| Fit Score | An evidence-backed score from 0 through 100 measuring support for the job's requirements and responsibilities. It is not a recruiter-call probability. |
| Preference Score | A campaign-weighted score from 0 through 100 measuring how desirable an eligible job is to the candidate. Unknown values are excluded and reduce confidence. It does not affect qualification. |
| Qualified Opportunity | An eligible Job Opportunity with a Fit Score of at least 75. |
| Daily Shortlist | The immutable zero-to-five newly presented Qualified Opportunities selected across all active campaigns for a candidate's local calendar day. Two is a target minimum, not an invariant. |
| Unactioned Shortlist Item | A presented opportunity the candidate has neither accepted nor dismissed. It stays actionable in its original digest but is not repeated unchanged. |
| Accept | The candidate's decision to pursue a shortlisted Job Opportunity. Acceptance starts an Application Candidacy. |
| Dismiss | The candidate's decision not to pursue a shortlisted Job Opportunity. |
| Application Candidacy | The candidate's pursuit of one Job Opportunity, from acceptance through tailoring, review, submission, and outcome tracking. |
| Tailored Resume Draft | The canonical Markdown projection of verified profile facts for one Application Candidacy. It may change selection, ordering, and wording but cannot add unsupported claims. |
| Draft Revision | An immutable saved version of a Tailored Resume Draft that can be selected for rendering. |
| Rendered Resume | An on-demand DOCX or PDF representation of one selected Draft Revision. |
| Submitted Application | An Application Candidacy the candidate has confirmed was sent to the employer. RIA cannot create this state autonomously. |
| Application Event | An immutable, dated event in a candidacy timeline, such as submitted, recruiter response, interview, rejection, withdrawal, or offer. |
| Void Event | An append-only correction that excludes a referenced mistaken Application Event from stage projections without erasing it. |
| Current Application Stage | A projection derived from a candidacy's Application Events; it is not an independently authoritative mutable status. |

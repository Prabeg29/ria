
## Status

Proposed. This record is being refined through domain-modeling interviews.

## Context

RIA currently accepts a resume and a job URL, scrapes the posting, and analyzes
the resume against that posting. The target product expands this into a daily
workflow that discovers software engineering roles, qualifies them against a
candidate profile, presents a small high-quality shortlist, and prepares an
application for roles the candidate chooses to pursue.

The product goal is to improve the candidate's chance of reaching an initial
recruiter conversation without fabricating experience or submitting an
application without the candidate's approval.

## Decisions

### Account ownership

V1 maps one authenticated account to exactly one Candidate. That account owns
the Candidate's Verified Profile, Search Campaigns, Daily Shortlists,
Application Candidacies, and retained artifacts. Every read and mutation is
scoped to that ownership boundary.

### Human authority

RIA may discover, analyze, rank, shortlist, and tailor application material.
The candidate must review and submit every application. RIA does not submit an
application autonomously.

### Candidate source of truth

The verified candidate profile is the canonical source of facts used for
analysis and tailoring. An uploaded base resume is an input artifact, not the
source of truth. Tailored resumes may select and reword verified facts but may
not invent or infer unsupported claims.

### Eligibility and fit

Work authorization is a hard eligibility rule evaluated before scoring. Other
attributes, including location, work mode, seniority, compensation, employer,
and role preferences, contribute to suitability but are not hard exclusions.

The match score is an evidence-backed fit score from 0 through 100. It measures
how strongly facts in the verified profile support the responsibilities and
requirements in the job description. It is not a prediction of recruiter-call
probability.

If a genuine mandatory job requirement has no supporting verified profile
fact, the Fit Score is capped below 75. Strong evidence for other requirements
cannot compensate for that gap and qualify the opportunity.

An explicit conflict between the posting's work-authorization requirement and
the Verified Profile makes the opportunity ineligible. When the posting omits
authorization language but the Candidate is generally authorized in the role's
jurisdiction, eligibility is uncertain rather than failed; the opportunity may
qualify but must show that uncertainty.

The initial fixed Fit Score rubric is:

| Dimension | Points |
|---|---:|
| Required qualifications | 40 |
| Comparable responsibility evidence | 30 |
| Seniority and scope | 15 |
| Preferred qualifications | 10 |
| Domain context | 5 |

An LLM may extract and classify requirements and map verified evidence, but the
application-owned rubric computes the score. Adjacent or transferable verified
experience may receive partial credit with an explanation. It must not be
presented as direct experience with the requested technology or domain.

Within each dimension, extracted items have equal weight by default. Weight may
increase only when the employer's text explicitly marks an item as essential,
core, or primary. Each item receives fixed evidence credit: `1.0` for direct
verified evidence, `0.5` for explained transferable evidence, and `0` when
unsupported.

A verified skill with no linked work, project, or achievement context receives
`0.5` credit. Full `1.0` credit requires verified contextual evidence of using
that skill.

Candidate preferences have a separate Preference Score; location, work mode,
compensation, and employer desirability do not alter the Fit Score or allow an
opportunity below 75 to qualify.

Preference Score is a campaign-configured weighted score from 0 through 100.
When a posting omits a preference value, that criterion is excluded from the
denominator and the score reports reduced confidence. Missing data is not
silently treated as either a match or mismatch.

Only opportunities scoring at least 75 are qualified for a daily shortlist.
The threshold is a hard quality gate. The desired shortlist size is two through
five opportunities, but the shortlist may contain fewer than two when too few
new opportunities qualify.

### Opportunity identity

A real-world opening is one canonical Job Opportunity, even when it is found on
multiple platforms. Platform-specific Source Listings retain provenance and
application URLs. An unchanged opportunity consumes at most one shortlist slot
and is not shown again on a later day.

A Job Opportunity remains open while at least one verified Source Listing still
accepts applications. Source closure and reopening change opportunity
availability but do not create a new opportunity.

Job descriptions are immutable, versioned snapshots. Changes to requirements,
responsibilities, seniority, or scope are material: they create a new Job
Description Version and trigger a new Fit Assessment. Employment terms and
listing availability are tracked separately. Identity-field changes require
duplicate-resolution review rather than automatic reassessment.

A materially changed opportunity may return to a daily shortlist only when it
is still unactioned and remains qualified. Accepted or dismissed opportunities
do not resurface automatically.

Source Listings are merged automatically only through deterministic shared
identity, such as an ATS requisition identifier. Semantic employer-title-
location matches create candidate-review proposals and do not merge records on
their own.

An incomplete discovery may be retained for a later fetch retry but cannot be
scored or shortlisted. Assessment requires employer, title, a viable
application URL, verified open state, and enough job-description content to
extract responsibilities and qualifications.

### Profile verification and versioning

RIA extracts proposed structured facts from a base resume. The candidate edits
and approves facts individually. Unapproved extracted content cannot support a
Fit Assessment or appear in a Tailored Resume Draft. Approving, editing, or
removing a fact creates a new Profile Version; existing assessments and
artifacts keep their original Profile Version reference.

A newly approved Profile Version is used for all future work and triggers
reassessment of unactioned opportunities and unsubmitted Application
Candidacies. Existing assessments and drafts remain as immutable history;
affected current drafts are marked stale until regenerated or explicitly kept.

### Campaigns and daily delivery

A candidate may have multiple active Search Campaigns. Each campaign defines
its own target roles, locations, work modes, seniority, compensation
preferences, sources, schedule participation, and maximum job age.

The candidate creates a campaign through structured targets and preferences.
RIA generates source-specific queries, but the candidate must preview and
approve those queries before campaign activation.

All active campaigns compete for one candidate-wide daily shortlist of no more
than five opportunities. RIA generates that digest once per day at the
candidate's configured local time and IANA time zone. The digest is not refilled
during the day.

The candidate views and actions the digest in the RIA web application. V1 does
not require email delivery or an API-only consumer workflow.

Qualified opportunities are ordered across campaigns by descending Fit Score,
then Preference Score, freshness, and campaign priority. Campaigns do not
receive reserved shortlist slots.

Job freshness is configured per campaign. When a source does not provide a
publication date, discovery time may be used for the freshness check, but the
date uncertainty must be visible to the candidate.

An unactioned shortlist item remains actionable in its original digest until
accepted, dismissed, or closed. It does not reappear unchanged or consume a
slot in a later digest.

### Candidate-controlled tailoring

A shortlisted opportunity initially contains its source links, fit score, and
supporting evidence. Tailoring begins only after the candidate accepts the
shortlist item. Acceptance creates an Application Candidacy; it does not mean
that an application has been submitted.

The canonical tailored artifact is a Markdown Tailored Resume Draft. The
candidate may edit it directly, and every save creates an immutable revision.
RIA renders a selected revision to ATS-friendly DOCX or PDF only when requested.
Rendered files are representations of the Markdown revision, not independent
sources of truth.

RIA retains uploaded base resumes, Markdown Draft Revisions, and every rendered
DOCX and PDF artifact. Retention does not make a rendered file authoritative;
each rendering references its source Draft Revision.

Artifacts remain until the candidate deletes an individual artifact or deletes
the account. Account deletion cascades through all candidate-owned domain data.

The Tailored Resume is the complete V1 application package. Cover letters,
screening answers, and recruiter outreach are outside V1.

### Post-submission scope

The first product version records application outcomes through recruiter
response, interview, rejection, withdrawal, and offer. Interview preparation,
contact management, and follow-up automation are outside the first version.

Only explicit candidate confirmation transitions an Application Candidacy to
submitted. Confirmation records the selected Tailored Resume Draft revision,
submission time, and application URL when known. Post-submission progress is an
append-only Application Event timeline; current stage is a projection of those
events rather than a mutable status that replaces history.

V1 uses the typed events `submitted`, `recruiter_response`, `interview`,
`rejected`, `withdrawn`, and `offer`. Events contain an occurrence time and may
contain notes; repeated interview events are valid. A mistaken event is
corrected by appending a `void` event with a reason and optional replacement,
not by erasing history.

Application outcomes provide analytics by campaign, source, and score band in
V1. They do not automatically change Fit Score rules or Preference Score
weights.

### Discovery methods

Discovery may use public job pages, official feeds or APIs, search-engine
results, and authenticated browser automation. Each source integration must
retain provenance and comply with the applicable access and usage constraints.

Authenticated discovery runs in a candidate-controlled browser agent or
extension. RIA receives discovered listing data, not reusable browser session
credentials.

The first usable discovery release supports Seek and public Greenhouse, Ashby,
and Lever boards. VC aggregators, Boolean search, and authenticated LinkedIn
discovery follow after this end-to-end release.

## Initial Domain Model

```text
Candidate
  owns one Verified Profile
  provides one or more Base Resume artifacts

Search Campaign
  configures sources, queries, preferences, and freshness
  starts Search Runs

Search Run
  discovers Source Listings
  resolves them to canonical Job Opportunities

Job Opportunity
  has one or more Source Listings
  has immutable Job Description Versions
  is checked for Eligibility
  receives a Fit Assessment against Profile and Job Description Versions
  may appear once in a Daily Shortlist

Daily Shortlist
  combines candidates from all active Search Campaigns
  contains zero through five qualified Job Opportunities

Application Candidacy
  begins when the candidate accepts a shortlisted opportunity
  may produce versioned Tailored Resume Drafts from verified profile facts
  renders a selected draft revision to DOCX or PDF on demand
  requires candidate action to become submitted
  records subsequent hiring outcomes as Application Events
```

## Draft Lifecycles

Opportunity consideration:

```text
discovered -> ineligible
           -> assessed -> below_threshold
                       -> shortlisted -> accepted
                                      -> dismissed
```

Application candidacy:

```text
accepted -> tailoring -> ready_for_review -> submitted
                                      \-> abandoned

submitted -> recruiter_response -> interview -> offer
         \-> rejected
         \-> withdrawn
```

These are domain states, not a commitment to matching database enum values.

## Invariants

- No application is submitted without an explicit candidate action.
- Every candidate resource is owned by and scoped to one authenticated account.
- No tailored claim lacks support in the profile version used to create it.
- Unapproved profile facts cannot support scoring or tailoring.
- Rendering a resume does not alter its selected Markdown revision.
- A work-ineligible opportunity cannot receive a shortlist slot.
- Uncertain work authorization must be visible on a shortlisted opportunity.
- An opportunity with a fit score below 75 cannot receive a shortlist slot.
- An unsupported mandatory requirement prevents a fit score of 75 or greater.
- A daily shortlist contains no more than five opportunities.
- A candidate receives no more than one generated shortlist per local day.
- Duplicate source listings do not consume additional shortlist slots.
- Semantic similarity alone cannot automatically merge Source Listings.
- Incomplete job data cannot produce a Fit Assessment or shortlist entry.
- A submission event cannot exist without an Application Candidacy.
- Only candidate confirmation creates a submission event.
- Application Events are append-only.
- Voided Application Events remain in history and are excluded from projections.
- A Job Opportunity is closed only when all verified Source Listings are closed.
- Unknown preference values reduce confidence rather than score.
- Every rendered resume references exactly one immutable Draft Revision.
- Account deletion removes all candidate-owned data and artifacts.

## Open Questions

- Source-specific access constraints within the selected first-release sources.
- Exact structured fields and validation rules for Campaign and Profile facts.
- Current-stage projection precedence for terminal Application Events.
- Operational retry, scheduling, and source rate-limit policies.

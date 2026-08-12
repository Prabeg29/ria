# Issue Tracker: Local Markdown

Issues and specifications for this repository live as Markdown files under
`.scratch/`.

## Conventions

- Store one feature in each `.scratch/<feature-slug>/` directory.
- Store its specification as `.scratch/<feature-slug>/spec.md`.
- Store implementation tickets as individual files under
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Record triage state as a `Status:` line near the top of each specification or
  ticket. Specifications published by `/to-spec` use `ready-for-agent`.
- Append conversation history under a `## Comments` heading when needed.

## Skill Operations

When a skill says to publish to the issue tracker, create or update the relevant
file under `.scratch/<feature-slug>/`. When a skill says to fetch a ticket, read
the referenced local Markdown file.

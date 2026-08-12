# Domain Docs

RIA is a single-context repository. Engineering skills must consume the shared
domain documentation before proposing or implementing changes.

## Read Before Exploring

- Read `docs/domain-glossary.md` and use its ubiquitous language.
- Read relevant records in `adr/` before working in an affected area.
- If a referenced document is absent, proceed silently rather than creating a
  speculative replacement.

## Vocabulary

Use glossary terms in issue titles, specifications, implementation plans, API
language, and tests. Do not replace defined concepts with synonyms that alter
their meaning.

If a required concept is missing, reconsider whether it is implementation
language rather than domain language. Record genuine domain gaps for a future
domain-modeling session.

## ADR Conflicts

Surface any conflict with an existing ADR explicitly. Do not silently override
a recorded decision.

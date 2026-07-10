# Verified project status

Date: 2026-07-10

## Release

- Package version: `0.2.0`
- Main extractor: `deterministic_protocol_v2`
- Record schema: `0.2.0`
- Development branch: `next-stage-protocol-events`

## Local verification

```text
Ruff                   PASS
pytest                  35 passed, 1 live test deselected
branch-aware coverage   85.31%
synthetic demo           PASS: 12/12 facts, F1=1.0
SQLite integrity         ok
wheel and sdist build    PASS
```

## Real-study scope

The current phase-aware result uses the existing 15-article, single-reviewer development set:

```text
v1 phase-aware fact F1            0.309
v2 phase-aware fact F1            0.665
v1 duration-plus-phase F1         0.000
v2 duration-plus-phase F1         0.459
v2 generated protocol events      54
v2 events with an explicit phase  50
```

This is not an independent test. The planned 60-article double-annotation study has software support but is not complete.

## Release boundaries

- No full real articles are included in the repository.
- No article-level predictions, exact quotes, or single-reviewer labels are published.
- No database response is treated as a literature-derived field.
- Service failure is `unresolved`, not `conflict`.
- Development results are labelled as development diagnostics.

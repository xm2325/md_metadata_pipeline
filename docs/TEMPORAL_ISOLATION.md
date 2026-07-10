# Provisional temporal isolation

## Purpose

This path creates a working annotation queue while the identifiers from one earlier held-out study are unavailable. It does not replace the locked confirmatory design.

## Status label

Every plan created by this path has:

```text
study_status = provisional_temporal_isolation
```

It must not be described as a locked confirmatory test set. The standard confirmatory command still requires at least 30 prior-study identifiers.

## Temporal rule

The current workflow queries open-access Europe PMC articles published from 2016 through 2020 and requires a known publication year. The query, page-response hashes, candidate manifest hash, plan hash, year window, seed, split identifiers, and exclusions are retained.

Temporal separation reduces the risk of reusing the recent pilot articles, but missing historical identifiers could still prevent a formal non-overlap proof. For that reason, the result remains provisional until the earlier held-out registry is complete.

## Machine full-text triage

The 60 selected JATS XML documents are downloaded into memory one at a time. The workflow does not save or publish the full XML. For each article it records:

- document and split identifiers;
- article title and article type;
- full-text SHA-256 and byte size;
- simulation-engine mentions;
- MD protocol term counts;
- biomolecular-domain term counts;
- method-section titles;
- machine-screen status and failures.

A strong machine signal requires an explicit MD expression, at least two additional protocol signals, a simulation-engine mention, and at least one protein, ligand, peptide, membrane, or nucleic-acid signal. A generic signal omits the named engine requirement. Review articles and weak or non-biomolecular articles are not marked machine eligible.

## Scientific boundary

Machine triage does not establish article eligibility, extraction correctness, or annotation quality. Human reviewers must confirm that the article reports performed biomolecular MD, identify the relevant protocol evidence, and apply the annotation guide independently.

No accuracy metric can be computed from the machine screen. It only reports corpus composition, accessibility, source hashes, and the size of the human-review queue.

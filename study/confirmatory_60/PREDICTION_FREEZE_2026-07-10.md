# Blinded protocol-event prediction freeze — 2026-07-10

This run froze deterministic machine predictions for the 60-paper provisional corpus before human annotation. It is an engineering and blinding result, not an extraction-accuracy result.

## Run identity

- Pull request: `#17`
- Merge commit: `595945b2c9081db4ac79fbc7389add1bcbdec8dc`
- Workflow run: `29089209351`
- Workflow head: `f8c3c17e6621f4384960f015b14e6db0d9208ce0`
- Extractor: `protocol_events_v1`
- Prediction commitment: `ab3c3f1e9c34a29055dc91871c632b96fd28df4c15e8dcf1c0ce2cdfdfc77e8c`

## Executed result

| Item | Result |
|---|---:|
| Articles requested | 60 |
| Articles completed | 60 |
| Failures | 0 |
| Machine-generated protocol events | 281 |
| Development placeholders | 30 |
| Validation placeholders | 10 |
| Locked-test placeholders | 20 |

The extractor produced 48 production, 67 equilibration, 21 heating, 8 minimisation, 11 analysis-window, 31 sampling-interval, and 95 unresolved-phase events. Every event contains a positive normalized duration and evidence tied to a method-like paragraph.

The event attributes include 281 normalized durations, 88 temperatures, 47 pressures, 39 time steps, 65 ensembles, and 13 replicate counts. These counts describe extractor output coverage only. They do not show whether the extracted values are correct.

## Source snapshot and evidence policy

Screening and prediction freezing used the same JATS byte snapshots in a temporary GitHub runner directory. For every selected article, the snapshot SHA-256 had to equal the previously recorded screening hash. Event evidence then had to reproduce the exact quote at the stored character offsets and match the paragraph SHA-256.

The temporary JATS directory was deleted before artifact upload. No article XML is present in the corpus, human-workpack, or machine-prediction artifacts.

## Blinding

Three separate artifacts were produced:

1. corpus metadata and commitments;
2. the human eligibility and annotation workpack;
3. machine predictions.

The human workpack contains 60 rows in final-plan order, blank reviewer A, reviewer B, and adjudication columns, two empty annotator JSONL files, and the annotation schema. It contains no machine predictions. Annotators must not receive the prediction artifact until independent annotation and adjudication are complete.

## Verified artifact digests

| Artifact | ID | SHA-256 digest |
|---|---:|---|
| Corpus metadata | `8226050594` | `1ba94af7f18c4d4e95eb2393f872ff845956aed2403e7c58165314a935dbef46` |
| Human workpack | `8226050921` | `2650d9f0a4b7720f69ca395348f29e34e7f56217e610eda96a6a4439dbfa57f6` |
| Machine predictions | `8226051312` | `bf5ecc7139755f91d2aaa7f8b8ef04e0859c3716bb8ffe643dc79427d97d4e0e` |

Internal artifact checksums passed. The prediction commitment and plan-to-screen commitment were independently recomputed. All 60 prediction source hashes matched the screening records, and the prediction process exit code was zero.

## Failures found and corrected during the run

The real workflow exposed four reproducibility problems that were corrected before freezing:

1. Europe PMC pagination used a single request per page; bounded retry, transport recovery, exponential backoff, and capped `Retry-After` handling were added.
2. Screening and prediction originally downloaded JATS independently; they now use one temporary source snapshot.
3. The unit normalizer handled `us` and `µs` but not Greek `μs`; all three forms are now equivalent.
4. A `0.0` duration expression reached the positive-duration schema; non-positive candidates are now skipped without discarding the article.

## Scientific boundary

The 281 events are machine candidates, not reference facts. No precision, recall, F1, event-grouping accuracy, or phase accuracy is reported. Human dual eligibility review, exact-span annotation, and adjudication are still incomplete. The corpus also remains provisional because 15 identifiers from a previous held-out set have not been recovered, so full non-overlap with all earlier evaluation articles has not been proven.

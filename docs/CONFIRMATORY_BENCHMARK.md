# Confirmatory benchmark protocol

## Status

The software for metadata retrieval, deterministic corpus selection, dual-annotation comparison, adjudication templates, and event-level evaluation is implemented. The 60-article study is not complete and no confirmatory accuracy result is claimed.

The corpus must not be locked until all articles used in earlier development and held-out studies are listed in `study/confirmatory_60/prior_article_ids.txt`. The preparation command requires at least 30 unique prior IDs. This rule prevents test-set reuse.

## Corpus construction

The saved Europe PMC query is:

```text
OPEN_ACCESS:Y AND HAS_FT:Y AND
(TITLE_ABS:"molecular dynamics" OR TITLE_ABS:"MD simulation")
```

Only metadata are retrieved by the corpus workflow. Each response page receives a SHA-256 hash. The candidate manifest stores the query, endpoint, page hashes, article identifiers, titles, DOI values, publication years, licences, source URLs, and software strata.

The deterministic plan uses seed `3997` and round-robin selection across reported simulation-software strata, followed by SHA-256 ranking. The split is:

- 30 development articles;
- 10 validation articles;
- 20 locked-test articles.

The plan stores a candidate-manifest hash and its own plan hash. Duplicate identifiers, missing PMC identifiers, unavailable full text, and prior-study articles are excluded with explicit reasons.

## Annotation

Two annotators independently record exact evidence spans, normalized values, units, event type, PDB identifiers, UniProt accessions, chain identifiers, and PDB–UniProt relations. They must not inspect model predictions or one another's export before first-pass completion.

Agreement is reported before adjudication at two levels:

1. semantic agreement over normalized fact, unit, and event type;
2. exact agreement adding paragraph identifier and character offsets.

Every disagreement is retained in a machine-readable adjudication template. No annotation is selected automatically.

## Locked evaluation

Extraction code, vocabulary tables, prompts, retrieval thresholds, normalization rules, and dependency versions are frozen before the 20 locked-test articles are opened.

Primary endpoint:

- micro F1 over event-linked attributes on the 20 locked-test articles.

Secondary endpoints:

- exact event F1;
- duration-plus-phase F1;
- duration-matched phase confusion;
- field-level precision, recall, and F1;
- article exact match;
- exact evidence-span accuracy;
- calibration and abstention;
- validation-state counts;
- article-bootstrap 95% confidence intervals.

Exact events, event attributes, and duration-phase pairs are counted as multisets. Repeated identical events are retained. The confusion matrix uses reference phase as rows and predicted phase as columns; `__missed__` and `__spurious__` represent unmatched duration events.

Pipeline failure is scored as zero recall for that article. Articles cannot be removed because they are difficult. Replacement is allowed only for a documented eligibility failure. Any system changed after test release is labelled post-hoc and cannot replace the frozen result.

## Commands

```bash
python scripts/query_europe_pmc.py \
  --output study/confirmatory_60/generated/candidates.json \
  --max-candidates 500

python scripts/prepare_confirmatory_benchmark.py \
  --candidates study/confirmatory_60/generated/candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --minimum-excluded 30 \
  --output study/confirmatory_60/generated/locked_plan.json

python scripts/compare_annotations.py \
  --annotator-a annotations/annotator_a.jsonl \
  --annotator-b annotations/annotator_b.jsonl \
  --output results/agreement.json \
  --adjudication-template results/adjudication.json

python scripts/evaluate_protocol_events.py \
  --predictions results/predictions.json \
  --references results/adjudicated_reference.json \
  --output results/event_metrics.json
```

Full article text is not committed unless redistribution rights are separately confirmed. Database validation is run after extraction and cannot populate reference labels.

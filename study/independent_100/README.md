# Independent 100-article study

## Purpose

This study is the next evidence tier after the completed provisional 60-article Roihu run. It
contains exactly 100 entirely new Europe PMC articles: 80 scale articles and a preselected,
sealed 20-article dual-human gold subset. The current 60 and every known prior development,
candidate-pool or run identifier are excluded mechanically before full-text screening.

## Leakage boundary

The `independent-100-corpus.yml` workflow performs metadata search, deterministic exclusion,
rule-based full-text triage, stratified gold selection and blind workpack construction. It does
not run the LLM and records `model_output_used_for_selection=false` and
`gold_predictions_generated=false` in the frozen plan. Article XML exists only in the ephemeral
Actions runner cache and is deleted before artifacts are uploaded.

The 80-article development split is scale-only and cannot support accuracy claims. The
20-article locked-test split must be independently annotated by two domain reviewers, fully
adjudicated and reference-frozen before its predictions can be generated or unsealed. Until then,
the study status is `independent_100_machine_screened_unreviewed`.

## Required sequence

1. Run the workflow and accept only an artifact whose `plan_audit.json` has `passed=true`.
2. Human-review eligibility for all 100 without model predictions.
3. Independently exact-span annotate and adjudicate the sealed gold20.
4. Freeze the model commit, prompt, schema, normalisation code and evaluation procedure.
5. Run scale80 on Roihu and report operational completeness without tuning on gold20.
6. Generate gold20 predictions separately, unseal once, and report per-field metrics with
   article-bootstrap uncertainty and complete failure accounting.

Scale and gold are now separated by an executable model-protocol freeze and gold authorization
gate. Batch v7 binds the source-independent prompt contract, and the freeze binds the exact scale80
GPU/CPU results, model snapshot, decoding configuration, normalisation and evaluation code. A
private gold20 source manifest cannot be authorized until both that scale freeze and the label-free
dual-human reference receipt pass. See
[`docs/INDEPENDENT_GOLD_PROTOCOL.md`](../../docs/INDEPENDENT_GOLD_PROTOCOL.md).

The code now enforces step 3 through
[`scripts/gold_reference_gate.py`](../../scripts/gold_reference_gate.py): two content-addressed
20-article submissions, explicit reviewed-zero states, source and paragraph hashes, distinct
annotators, complete item-level adjudication, a private reference bundle and a label-free public
freeze receipt. This is infrastructure, not completed annotation. Real labels must remain in
access-controlled storage outside this public checkout; Actions exercises only synthetic fixtures.

## Current progress

The live GitHub Actions run completed corpus construction **100/100** on 2026-07-15: 80 scale
articles and a sealed gold20 passed the non-overlap/seal audit. On 2026-07-16 the label-free Roihu
path then completed scale inference **80/80**, CPU integration **80/80** and the pre-gold model
protocol freeze. This does not mean that the whole scientific study is complete. Human eligibility
review is 0/100, gold dual annotation/adjudication is 0/20, and gold prediction/evaluation is 0/20.
See [`RUN_2026-07-15.md`](RUN_2026-07-15.md) and
[`RUN_SCALE80_2026-07-16.md`](RUN_SCALE80_2026-07-16.md).

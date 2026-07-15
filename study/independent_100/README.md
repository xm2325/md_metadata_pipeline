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

## Current progress

The selection infrastructure is implemented. A selected article does not count toward the future
independent 100 until the GitHub Actions artifact exists and passes the non-overlap/seal audit;
human-gold progress remains zero until two independent annotations and adjudication are frozen.

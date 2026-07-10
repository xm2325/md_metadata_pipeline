# Eligibility-first corpus locking

## Why the order matters

Assigning development, validation, and test labels before article eligibility is known creates a replacement problem. If ineligible articles are replaced independently within each split, the final split composition may depend on machine screening or reviewer decisions. Version 0.8 instead separates candidate ordering, eligibility review, and split assignment.

## Stage 1: ordered pool with reserves

A deterministic, software-stratified pool is selected from the candidate metadata manifest. The default size is 120: enough for a 60-article target plus reserves. The pool stores its selection seed, temporal rules, prior-study exclusions, candidate-manifest hash, article order, and pool hash.

No article receives a development, validation, or locked-test label at this stage.

## Stage 2: full-text machine triage

Each selected JATS document is downloaded into memory and hashed. The workflow records limited metadata and lexical protocol/biomolecular signals but does not save article XML. Machine status is an audit and workload signal only.

## Stage 3: split-blind human eligibility

The review template omits:

- pool positions;
- future split labels;
- machine-screen status;
- engine mentions;
- protocol-term counts.

It includes the article identifier, title, year, source URI, article type, full-text hash, and method-section titles. Two reviewers independently choose `eligible`, `ineligible`, or `uncertain`, with a reason and reviewer identifier.

Decision agreement and full-text hash conflicts are reported before adjudication. Disagreements receive a machine-readable adjudication template. Hash conflicts block adjudication until both reviewers use the same source document.

## Stage 4: final corpus locking

The finalizer reads adjudicated `eligible` or `ineligible` decisions in the original pool order. It selects the first 60 eligible articles. A missing adjudicated decision before the sixtieth eligible article is a hard error.

Only after this selection does the code assign splits using a separate split seed. Articles are ordered by a split-seed hash and assigned with a repeating 3:2:1 development:test:validation cycle, producing exactly 30 development, 20 locked-test, and 10 validation articles.

The locked output retains:

- source pool hash;
- adjudication hash;
- split seed;
- number of pool articles reviewed before the target was reached;
- split assignment method;
- final plan hash.

## Commands

```bash
python scripts/prepare_eligibility_pool.py \
  --candidates historical_candidates.json \
  --excluded-ids study/confirmatory_60/prior_article_ids.txt \
  --pool-size 120 \
  --publication-year-min 2016 \
  --publication-year-max 2020 \
  --require-known-year \
  --output screening_pool.json

python scripts/screen_eligibility_pool.py \
  --pool screening_pool.json \
  --output fulltext_machine_screen.json

python scripts/create_eligibility_review_template.py \
  --pool screening_pool.json \
  --screen fulltext_machine_screen.json \
  --output blind_review_template.json

python scripts/compare_eligibility_reviews.py \
  --review-a reviewer_a.json \
  --review-b reviewer_b.json \
  --output eligibility_agreement.json \
  --adjudication-template eligibility_adjudication.json

python scripts/lock_after_eligibility.py \
  --pool screening_pool.json \
  --adjudicated adjudicated_eligibility.json \
  --output final_30_10_20_plan.json
```

## Limits

The software does not create two independent human reviews. Machine triage cannot be copied into the human decision fields. A final corpus cannot be reported as human-adjudicated until two reviewers and an adjudicator have completed the corresponding files.

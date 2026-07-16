# Dual-annotation and gold-reference guide

Each annotator works from the same frozen article set and produces an independent export.
Annotators must not inspect model predictions or the other annotator's file before first-pass
completion. Real locked-test labels must stay in access-controlled storage outside the public
checkout; GitHub Actions validates the gate with synthetic fixtures only.

## Annotation facts

Each fact records:

- a stable annotation and document identifier;
- annotator identifier;
- field name, normalized value, and unit;
- MD event type;
- paragraph identifier and SHA-256;
- zero-based character start and end offsets;
- an exact quote copied from the paragraph;
- an optional note.

The base schema rejects quote lengths that do not equal `end_char - start_char`. The gold gate also
requires `paragraph_sha256` and verifies that all facts bind the submission owner, article and
frozen source hash.

Every gold article has an explicit `complete_with_facts` or `complete_no_facts` state. This prevents
an empty file or omitted article from being misread as a reviewed negative. An ineligible article
cannot contain reference facts.

## Independent comparison

The general comparison command reports:

1. semantic agreement: normalized fact, unit, and event type;
2. exact agreement: semantic agreement plus paragraph and character span.

```bash
python scripts/compare_annotations.py \
  --annotator-a annotations/annotator_a.jsonl \
  --annotator-b annotations/annotator_b.jsonl \
  --output results/agreement.json \
  --adjudication-template results/adjudication.json
```

For the independent gold20, use the stricter gate below. The unsealed submission is a JSON object
matching `mdmeta.gold-annotation-submission.v1`; it contains exactly 20 article envelopes and may
omit `submission_sha256` before sealing.

```bash
python scripts/gold_reference_gate.py seal-submission \
  --plan "$PRIVATE/frozen_plan.json" \
  --screen "$PRIVATE/fulltext_machine_screen.json" \
  --plan-audit "$PRIVATE/plan_audit.json" \
  --input "$PRIVATE/annotator_a.unsealed.json" \
  --output "$PRIVATE/annotator_a.sealed.json"

python scripts/gold_reference_gate.py seal-submission \
  --plan "$PRIVATE/frozen_plan.json" \
  --screen "$PRIVATE/fulltext_machine_screen.json" \
  --plan-audit "$PRIVATE/plan_audit.json" \
  --input "$PRIVATE/annotator_b.unsealed.json" \
  --output "$PRIVATE/annotator_b.sealed.json"
```

The gate rejects duplicate IDs, missing articles, source drift, missing paragraph hashes, reused
annotator identities, exposure to model predictions and broken content commitments.

## Adjudication and freeze

Generate the private comparison and a deterministic decision template only after both sealed
submissions exist:

```bash
python scripts/gold_reference_gate.py prepare-adjudication \
  --plan "$PRIVATE/frozen_plan.json" \
  --screen "$PRIVATE/fulltext_machine_screen.json" \
  --plan-audit "$PRIVATE/plan_audit.json" \
  --annotator-a "$PRIVATE/annotator_a.sealed.json" \
  --annotator-b "$PRIVATE/annotator_b.sealed.json" \
  --output-template "$PRIVATE/adjudication.json" \
  --output-private-comparison "$PRIVATE/agreement.private.json"
```

Every derived eligibility or exact-fact disagreement gets a content-addressed ID. Adjudicators must
resolve every ID, provide a note and recompute `adjudication_sha256`. The mode can be consensus of
the two original annotators or an independent third reviewer; the identifier constraints differ
accordingly.

Freeze only after the adjudication status is `complete`:

```bash
python scripts/gold_reference_gate.py freeze \
  --plan "$PRIVATE/frozen_plan.json" \
  --screen "$PRIVATE/fulltext_machine_screen.json" \
  --plan-audit "$PRIVATE/plan_audit.json" \
  --annotator-a "$PRIVATE/annotator_a.sealed.json" \
  --annotator-b "$PRIVATE/annotator_b.sealed.json" \
  --adjudication "$PRIVATE/adjudication.json" \
  --frozen-at-utc 2026-07-16T12:00:00Z \
  --operator-run-id independent100-gold20-freeze-1 \
  --output-private-reference "$PRIVATE/gold20.reference.private.json" \
  --output-public-receipt "$PUBLIC/gold20.freeze-receipt.json"
```

The private output contains human labels and must never be committed or uploaded as a public
Actions artifact. The public receipt contains only content commitments and completion assertions;
it deliberately excludes article IDs, labels, eligibility totals, fact totals and agreement
statistics. A SHA-256 receipt is tamper-evident provenance, not an identity signature. If formal
authenticity is required, sign the receipt with the institution's approved signing service.

No accuracy claim is allowed until the model/configuration freeze is separately committed, gold20
predictions are generated without access to this reference, and evaluation is unsealed once.

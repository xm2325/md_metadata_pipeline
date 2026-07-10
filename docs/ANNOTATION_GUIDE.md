# Dual-annotation guide

Each annotator works from the same frozen article set and produces an independent JSONL export. Annotators must not inspect model predictions or the other annotator's file before first-pass completion.

Each row records:

- a stable annotation and document identifier;
- annotator identifier;
- field name, normalized value, and unit;
- MD event type;
- paragraph identifier;
- zero-based character start and end offsets;
- an exact quote copied from the paragraph;
- an optional note.

The schema rejects quote lengths that do not equal `end_char - start_char`.

Agreement is reported at two levels:

1. semantic agreement: normalized fact, unit, and event type;
2. exact agreement: semantic agreement plus paragraph and character span.

All disagreements are written to an adjudication template. The allowed decisions are `accept`, `reject`, and `replace`. No candidate is accepted automatically.

```bash
python scripts/compare_annotations.py \
  --annotator-a annotations/annotator_a.jsonl \
  --annotator-b annotations/annotator_b.jsonl \
  --output results/agreement.json \
  --adjudication-template results/adjudication.json
```

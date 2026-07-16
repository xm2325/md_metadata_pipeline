# Risk-based human review

The production pipeline does not equate machine output with truth, but it also does not require
two people to re-check every field. It emits a deterministic, database-bound review queue with one
of three outcomes per article:

| Tier | Meaning | Default action |
|---|---|---|
| `auto_accept` | No implemented uncertainty trigger fired | Accept provisionally; retain in the queue manifest and audit a deterministic sample |
| `single_review` | A routine or elevated uncertainty trigger fired | One reviewer resolves the named prompt from the bound evidence/source |
| `dual_independent` | A critical ambiguity fired, or the purpose is reference benchmarking | Two reviewers annotate independently and blinded, then adjudicate disagreements |

`auto_accept` means only that the versioned policy detected no review trigger. It is not a claim
that a record is ground truth. The default 5% deterministic audit sample estimates missed-error
drift among apparently high-certainty records. Production operators should calibrate the threshold
and sampling rate against reviewed data rather than treating `0.8` or `5%` as universal constants.

## What the reviewer receives

Every routed item names:

- the uncertainty code and a plain-language summary;
- the concrete question the reviewer must answer;
- the article and source URI;
- the relevant field, value, event ID, identifier, external endpoint or report commitment;
- exact paragraph/span coordinates and the source-context hash where literature evidence exists;
- the conditions that require escalation to a second reviewer.

The queue deliberately excludes evidence quotes, external payloads, sequences and server-local
paths. Reviewers resolve locators against the governed source snapshot. This keeps the queue small
and avoids silently creating another uncontrolled copy of source material.

Current triggers include low-confidence facts/events, unknown event phases, missing evidence,
incompatible operator-declared single-valued facts, unresolved or conflicting PDB/UniProt/SIFTS
checks, overlapping residue mappings to different accessions, partial pipeline stages, a method
signal without a protocol event, and missing/unresolved/conflicting PDBe-KB enrichment. A
`not_applicable` upstream result is not itself uncertainty; it records a valid no-data outcome.

## When double review is necessary

Forced, blinded double review is justified in these cases:

1. **Gold/reference data and reported accuracy.** Every item must be reviewed twice regardless of
   model confidence. Selecting only uncertain items would bias the reference set and its metrics.
   The sealed gold20 process therefore remains a separate strict gate.
2. **Critical semantic ambiguity.** Examples are incompatible extracted values for a field that
   should be single-valued, missing evidence for an asserted event, an external scientific
   conflict, or overlapping PDB-chain residues mapped to different UniProt accessions.
3. **Escalation after first review.** A second independent reviewer is required if the first
   reviewer changes a scientific value or evidence span, cannot resolve the item, finds two
   plausible interpretations, or disagrees with an automatic acceptance sampled for QC.
4. **Commissioning or material change.** A blinded, stratified subset of both accepted and routed
   records should be double-reviewed after a new model, prompt, policy, source version or domain is
   introduced. This measures drift; it does not require permanent double review of every item.
5. **High-impact downstream use.** If records drive regulated, clinical, safety-critical or other
   consequential decisions, governance may require double review for that entire release scope.
   This repository's current research-metadata use case does not make such a claim.

Routine low confidence, a transient upstream failure, missing optional enrichment, or an expected
coverage gap normally needs one reviewer first. If that reviewer resolves the issue without a
material change or ambiguity, a second reviewer adds cost without a defined risk-control benefit.

The current scale80 queue contains 2 provisional automatic acceptances, 78 targeted single-review
items and no direct critical double-review item. Those 78 decisions have not been performed. Any
first reviewer who changes a value/span, cannot decide or finds competing interpretations must
still escalate that item. `WORKFLOW_COMPLETE`, green CI and a zero direct-dual count are technical
states; none is a substitute for recording the required human decisions before scientific release.

## Commands

Build the production queue from a checkpointed schema-v2 database:

```bash
mdmeta-human-review build \
  --database records.sqlite \
  --model-summary model-batch-summary.json \
  --output human-review-queue.json \
  --git-commit "${GIT_COMMIT:?set exact 40-character commit}" \
  --purpose production_triage \
  --confidence-threshold 0.8 \
  --audit-sample-rate 0.05 \
  --audit-salt release-2026-07

mdmeta-human-review verify \
  --queue human-review-queue.json \
  --database records.sqlite \
  --model-summary model-batch-summary.json
```

For an independently annotated benchmark workpack, use
`--purpose benchmark_reference --audit-sample-rate 0`. This classifies every article as
`dual_independent`; it does not replace the private submissions, blinded comparison, adjudication
and label-free public receipt defined in the sealed gold20 protocol.

When supplied, the model summary adds per-article no-task, evidence-rejection and
generation-rejection signals. Accepted events with rejected attributes and zero-event records with
fully rejected paragraphs are routed; rejected paragraphs alongside other accepted events remain
covered by the deterministic audit sample. Its SHA-256 is bound into the queue, so failures
discarded before database integration cannot silently disappear from triage.

No literature field is assumed globally single-valued by default: one paper may legitimately use
multiple engines or force fields. Operators may repeat `--single-value-field FIELD` only when the
release data product defines that field as single-valued; incompatible values then become a
critical double-review trigger.

The queue is reproducible: it has no wall-clock timestamp, is sorted by document ID, binds the
source database and optional model-summary SHA-256 values, records the software version, exact Git
commit and full policy, and carries a commitment over all content.

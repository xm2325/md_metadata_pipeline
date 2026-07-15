# Independent scale80 to gold20 protocol

This protocol prevents the locked-test articles or human labels from influencing model selection,
prompt/schema changes, normalisation code or evaluation code. Passing software tests does not
authorize gold inference; two completed scientific evidence chains are required first.

## Gate A: scale80 and model-protocol freeze

Run the accepted scale80 manifest through the GPU extraction and CPU integration jobs. The run must
use batch schema v7, which records both a source-independent prompt-contract SHA-256 and the
source-bearing prompt SHA-256 for every task. It must process exactly 80 pre-staged, hash-matched
articles, classify every task, pass the temperature-zero within-run repeat, and complete 80/80 CPU
integration.

Then run this inside the verified, extracted source archive on CSC:

```bash
python scripts/freeze_independent_model.py freeze-protocol \
  --scale-manifest "$PRIVATE/scale80/source_manifest.json" \
  --scale-result "$PRIVATE/scale80/gpu/result.json" \
  --scale-integration-result "$PRIVATE/scale80/cpu/integrated/summary.json" \
  --model-manifest "$MODEL_ROOT/model-manifest.json" \
  --source-root "$PRIVATE/scale80/gpu/source" \
  --source-archive "$PROJAPPL/source/md-metadata-pipeline.tar" \
  --gpu-environment "$PRIVATE/scale80/gpu/environment.txt" \
  --gpu-summary "$PRIVATE/scale80/gpu/gpu-summary.json" \
  --integration-environment "$PRIVATE/scale80/cpu/environment.txt" \
  --integration-database "$PRIVATE/scale80/cpu/integrated/records.sqlite" \
  --frozen-at-utc 2026-07-16T12:00:00Z \
  --operator-run-id independent100-scale80-model-freeze-1 \
  --output "$PRIVATE/model-protocol-freeze.json"
```

The gate verifies and binds:

- the exact scale80 source manifest, GPU result and 80-record integration result;
- source commit and actual archive digest;
- raw-file hashes for both results, the model/source manifests, GPU/CPU environments, GPU summary
  and integrated SQLite snapshot;
- immutable model/tokenizer revision, licence and snapshot manifest;
- decoding configuration and observed runtime;
- prompt v1 and response-schema v3 commitments;
- extraction, evidence validation, normalisation, integration and evaluation files.

Changing any frozen implementation file requires a new source commit and a new scale80 run. The
completed historical 60-article batch remains valid evidence under v6, but it cannot authorize the
independent gold20 because it predates the source-independent prompt commitment and uses a different
corpus.

## Gate B: dual-human reference freeze

Independently annotate and adjudicate gold20 using the procedure in
[`ANNOTATION_GUIDE.md`](ANNOTATION_GUIDE.md). Keep the private reference inaccessible to the model
operator. Only its label-free public receipt crosses the boundary.

## Gate C: authorize one gold20 prediction manifest

After both Gate A and Gate B pass, combine their commitments with the accepted frozen plan:

```bash
python scripts/freeze_independent_model.py authorize-gold20 \
  --plan "$PRIVATE/selection/frozen_plan.json" \
  --screen "$PRIVATE/selection/fulltext_machine_screen.json" \
  --plan-audit "$PRIVATE/selection/plan_audit.json" \
  --model-freeze "$PRIVATE/model-protocol-freeze.json" \
  --human-reference-receipt "$PUBLIC/gold20.freeze-receipt.json" \
  --authorized-at-utc 2026-07-16T13:00:00Z \
  --operator-run-id independent100-gold20-authorization-1 \
  --output-private-gold-manifest "$PRIVATE/gold20.prediction-source.json"
```

The output contains the 20 source IDs and hashes but no human labels. It is a private inference
input, not a public artifact. The existing Roihu staging/GPU scripts accept it as an external
manifest only when its file SHA-256 is supplied and it resides under the submitting user's private
project path.

Generate predictions once with the frozen model contract, commit their content hash, and only then
unseal the private reference for evaluation. Never use gold metrics to modify this frozen model and
report them as if they were still held out. Any post-unseal change starts a new development cycle
and needs a new independent test set.

GitHub Actions validates these gates using synthetic articles, model metadata and human receipts.
It never creates, uploads or evaluates the real gold labels.

# Roihu model-backed literature experiment

## Status and purpose

This document is the execution protocol. Its bounded response-v3 1 → 5 → 60 chain completed on
2026-07-15: GPU jobs 189325, 189333 and 189353 and CPU integration jobs 189330, 189352 and 189371
all passed. The 60-article run classified 740/740 tasks with zero generation rejections, and the
CPU integration produced 60/60 records with zero failures. Commitments, aggregate results,
preserved failures and reproducibility limits are in the
[2026-07-15 1 → 5 → 60 run report](../study/roihu_llm_60/RUN_2026-07-15.md). The infrastructure
smoke result remains documented in the
[2026-07-15 GH200 smoke report](../study/roihu_gpu_smoke/RUN_2026-07-15.md).

The immediate experiment is designed to produce bounded evidence relevant to EMBL-EBI JR3997:

- reproducible local-model extraction of experimental metadata from literature;
- exact-span and schema validation with no silently discarded model response;
- model-backed integration with PDBe, UniProt and SIFTS-derived validation; and
- an auditable CPU → GPU → CPU workflow on one CSC Roihu GH200.

It does not turn the current provisional corpus into a confirmatory benchmark. The current
`study/integration_60/source_manifest.json` contains 60 machine-screened articles in a 30/10/20
layout after a complete current-source audit and deterministic two-row rebuild. Its study status is
`provisional_operational_multi_rebuild_not_accuracy`. In particular, the 20 rows whose split label
is `locked_test` are placeholders and must not be described as an independent locked test set.

The independent 100-article study described later is separate from the immediate 1 → 5 → 60
execution and is not a current accuracy result. Its corpus selection is complete: 80 scale articles
plus a sealed 20-article gold subset. Scale inference, independent human annotation and gold
evaluation remain pending.

## Frozen model candidate

The planned model is:

| Field | Frozen value |
| --- | --- |
| Hugging Face repository | `Qwen/Qwen2.5-7B-Instruct` |
| model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| tokenizer revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| declared licence | `apache-2.0` (Apache-2.0) |
| access policy | ungated; no Hugging Face token |
| remote model code | disabled |
| inference runtime | CSC `python-vllm/0.19.1` module, BF16, one GH200 |

The revision is a full commit identifier, not a mutable branch or tag. The CPU staging job must
query the model metadata without a token, require the declared licence, reject a gated model,
download only that revision and hash every snapshot file. The GPU job must verify the generated
model manifest and every file before starting offline inference. “Ungated” and “Apache-2.0” are
inputs to be revalidated by the staging code, not assumptions that bypass the gate. The upstream
[model card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) remains the authoritative source for
model-specific limitations and permitted use.

The extraction configuration is also frozen for a comparable run: schema-constrained decoding,
temperature `0`, seed `3997`, BF16, maximum model length `16384`, maximum output `4096` tokens,
batch size `32`, tensor parallel size `1`, and GPU memory utilisation target `0.8`. A change to the
model, revision, prompt, schema, corpus, decoding settings or runtime creates a new experiment and
must not silently replace an accepted result.

## Immediate 1 → 5 → 60 design

Use one immutable source archive and one source-manifest commitment throughout. Stage all 60
frozen JATS inputs before occupying a GPU so that network retrieval, licence checks and input hash
validation happen on CPU. Reuse the same verified model snapshot and JATS cache for all GPU jobs.
The technical-gate article is the first manifest row and the five pilot articles are the first five
manifest rows, selected before seeing model output.

Submit CPU staging and integration jobs through the SSH alias `roihu_cpu`; submit GPU inference
jobs through `roihu_gpu`. The CPU and GPU clusters share the approved project storage but have
different login nodes, architectures and Slurm job namespaces. Do not submit a CPU job from the GPU
login or a GPU job from the CPU login, and do not rely on a cross-cluster Slurm dependency. Verify
each preceding result explicitly before submitting the next job through the other alias.

| Gate | Partition and bound | Work | Required output |
| --- | --- | --- | --- |
| 0. source freeze | local submission host | Require a clean committed revision; create a secret-free `git archive` whose root contains `.mdmeta-source-commit`; verify that the marker equals the full commit and record the archive SHA-256. | immutable, self-identifying source archive |
| 1. CPU stage | submit through `roihu_cpu`; `small`, one task, 4 CPUs, 16 GiB, at most 1 hour | `hpc/roihu/stage_inputs.sbatch` stages the exact model revision and all 60 JATS documents from `study/integration_60/source_manifest.json`. | verified source marker, model manifest, 60-row JATS stage manifest, checksums and environment record |
| 2. GPU technical gate | submit through `roihu_gpu`; `gputest`, one GH200, 16 CPUs, at most 15 minutes | `hpc/roihu/llm_extract.sbatch` runs only the first manifest article with offline model access. | one-article full private result, compact summary, checkpoint, GPU samples and checksums |
| 3. CPU technical integration | submit through `roihu_cpu`; `small`, one task, 4 CPUs, 16 GiB, at most 1 hour | `hpc/roihu/model_integration.sbatch` binds the one-article prediction to frozen JATS and exercises live PDBe/UniProt/SIFTS-derived validation. | one integrated record, SQLite database, validation cache, summary and checksums |
| 4. GPU five-article pilot | submit through `roihu_gpu`; `gputest`, one GH200, 16 CPUs, at most 15 minutes | Rerun the exact frozen configuration on the first five manifest rows. | coherent five-article result, compact summary, checkpoint, GPU samples and checksums |
| 5. CPU pilot integration | submit through `roihu_cpu`; `small`, one task, 4 CPUs, 16 GiB, at most 1 hour | Integrate the five predictions and perform live identifier/mapping validation. | five integrated records, SQLite database, validation cache, summary and checksums |
| 6. GPU frozen 60 | submit through `roihu_gpu`; one GH200 on the appropriate production GPU partition | Rerun the same frozen configuration over all 60 rows. Request wall time from measured pilot runtime plus documented headroom; use `gpumedium` if the justified request exceeds the 15-minute test limit. | one coherent 60-article result and compact summary with all tasks classified |
| 7. CPU 60 integration | submit through `roihu_cpu`; `small`, bounded from the pilot | Integrate all 60 predictions using the same source/model commitments, retaining explicit per-article failures. | 60 requested records, SQLite database, compact integration summary and checksums |

Do not request more than one GPU for this experiment. The five-article pilot repeats the technical
article, and the 60-article batch repeats the first five, so each stage produces one self-contained
committed result. Compare repeated response commitments across stages and investigate differences,
but do not hide them or assume that different batch shapes are bitwise identical.

The GPU is used only for local inference. Source acquisition and model staging happen before the
GPU allocation; identifier validation, record construction and database writing happen afterward
on CPU. This keeps paid GPU time attributable to the task that needs it and makes failures easier
to isolate.

## Source-drift recovery

A frozen JATS digest is an evidence commitment, not a value to update when Europe PMC changes its
current XML representation. First try to recover the exact frozen bytes from an approved immutable
copy and require them to reproduce the committed SHA-256. If those bytes cannot be recovered, do
**not** replace the manifest digest with the hash of the newly downloaded XML and do not treat the
changed document as the same frozen input.

A deterministic reserve substitution is allowed only before any model inference for that corpus
has started. It must follow all of these rules:

1. Retrieve the original GitHub Actions corpus artifact named by the source manifest. Verify the
   outer artifact digest and the stored SHA-256 of every component used to reconstruct selection,
   including `provisional_temporal_plan.json` and `fulltext_machine_screen.json`.
2. In the original plan's `rejected_or_reserve` order, select exactly the first row whose reason is
   `eligible_reserve_not_selected`. Do not choose a more convenient replacement and do not skip to
   a later reserve if the first reserve fails validation without a reviewed protocol amendment.
3. Locate that document's record in the verified original screen component. Fetch its current XML
   and require both `full_text_sha256` and `xml_size_bytes` to equal the screen record. A matching
   title, identifier or screen status alone is insufficient.
4. Replace only the unrecoverable article at its original array position. Preserve the selected
   corpus size, position and assigned split; do not reshuffle any other article or recalculate the
   selection using current upstream data.
5. Create a new self-committed source manifest that records the superseded manifest, failed
   document, failure job, verified artifact/component commitments, deterministic reserve rule and
   replacement document. Commit that manifest, then create and validate a new git archive with a
   matching root `.mdmeta-source-commit`. Never reuse the superseded commit or source archive for
   the remediated run. The recovery job must require the failed job identifier and the exact
   observed drifted SHA-256 and byte size as inputs; merely proving that the current bytes differ
   from the frozen commitment is insufficient.
6. Preserve the failed run directory, Slurm accounting, logs, checksum evidence and drift error.
   Do not overwrite or delete them after a replacement succeeds.

If inference has already started, the affected run fails as a whole: no in-place substitution,
partial-result merge or hash update is permitted. Any restart must be reviewed as a new corpus
revision with a new manifest, commit, archive and run identifier.

### Historical one-row recovery

CPU staging job `185329` detected that the current XML for `PMC6316748` no longer matches the frozen
source. The manifest commits SHA-256
`cdbfd10f7e85a4042ebda7317b06cf963061f05e00d99168c03a5ed7e03a337d` and 105,780 bytes; the
current response has SHA-256
`51d20c7e8b35720e9150d2118d274cf2e5048a64fdaf7905552210530a87d52a` and 102,369 bytes. A
separate check of the other four documents in the planned first-five gate (`PMC7560594`,
`PMC6962038`, `PMC7439393` and `PMC5743237`) matched their frozen hash and size. This limited check
is not evidence that all 60 documents are currently recoverable.

The original artifact commitments used for reserve recovery have been verified as:

- GitHub artifact digest:
  `sha256:470bb9fb223703413a3e0f287ce410adcdb9e5c7ea09c1d3bd15687437ef0966`;
- `provisional_temporal_plan.json` file SHA-256:
  `49f2608deff0641a47c87e7be4e65c1d34f2df33f63b8dc218797f12a52b3737`; and
- `fulltext_machine_screen.json` file SHA-256:
  `3cfcfeb7c74e4beb3d4b7bd69c9ff97c2f837a78314a2e71fc3c38ae1353b877`.

In that verified original order, `PMC6994855` is the first
`eligible_reserve_not_selected` record. Its original screen and current XML both report SHA-256
`169ced75f7adf4ed9ab18bf28ec08ecd8ab76414dd81367ae9f277702ddc5a4d` and 87,028 bytes.

The recovery implementation at commit `8cf6b1f6c9e9b5662ac00de7db1bb724bfba8480` passed focused
Roihu CPU validation job `185648` with 37 tests, zero failures and zero errors. Source substitution
job `185650` then completed with exit code zero and replaced only position 1 in the development
split. The output contains 60 unique articles with 59 parent rows unchanged and records that no
model output was used. The accepted replacement manifest and compact report are stored at
`study/integration_60/source_manifest_superseded_185650.json` and
`study/integration_60/source_substitution_report.json`.

The manifest has internal commitment
`b88942f8959fe85ca18b3fe333d9a4fc06aef93a1103a080a6c6ad3ff9aac96b` and file SHA-256
`404a43cd1297b8803f75d4a50d356887adbecdd7cdc0b29d6d1fe196e1cb6a23`. The report has internal
commitment `e1987d67e5aef0b51f80047970efcb501a9faa3f14116e946ac3a9423193086b` and file SHA-256
`81695496dda707dcb715b90877123a5030eed3793a8027c7c123b9d0eca51fa4`. Job `185329` remains
preserved failed drift evidence rather than a successful stage or model run. This one-row manifest
is immutable superseded lineage; it is not the current operational manifest.

### Complete full-pool audit and deterministic rebuild

The one-row recovery above did not make the remaining 59 source commitments recoverable. Staging
job `185656` verified the existing model snapshot, then stopped with exit code 1 when Europe PMC's
current XML for `PMC6423238` differed from its frozen SHA-256. No GPU inference started. The
one-row manifest and job `185650` remain immutable lineage evidence and were not mutated through a
second sequential substitution.

Roihu CPU audit job `185845` then examined the original 60 selected rows and all 18 original
`eligible_reserve_not_selected` rows without early stopping. It completed 78/78 retrieval
classifications with zero unresolved rows: 58 selected rows were exact matches, two selected rows
required replacement, 17 reserves were exact matches and one reserve was diagnostic rather than a
matching cache entry. The private cache contained 75 exact payloads and three diagnostic payloads.
The compact accepted audit is
`study/integration_60/source_pool_audit.json`; it has internal commitment
`62d9c0063a47c0b86a52723a2262c72116f5902c0997c32ee49cf9e5ff57f5ea` and file SHA-256
`ab4f6fc8a799aec35c5fdb177f67e82fba1482935ac1df9931a80eb820340eca`.

Because the audit was complete and had enough valid reserves, offline rebuild job `187089` applied
the predeclared first-N policy in one generation. It mapped original position 1 `PMC6316748` to
original reserve rank 1 `PMC6994855`, and original position 42 `PMC6423238` to original reserve
rank 2 `PMC7603383`. The other 58 rows stayed unchanged; all positions, 60 unique identifiers and
the provisional 30/10/20 split counts were preserved. No model output, article topic or downstream
result entered the decision.

The current operational manifest is `study/integration_60/source_manifest.json`, with internal
commitment `b73387925f866162c42863aa7957c759c1404b5ed9229c8d6b57ed4707a2bdfe` and file SHA-256
`2c0e0275b2b3303607ccb30e9632994d86a2d71367dcc3cd73581e59d1bbd74e`. The compact rebuild
report is `study/integration_60/source_pool_rebuild_report.json`, with internal commitment
`1bae366076d02f606238424796957576d56d15e5727d4ee37ef5f324bec5a491` and file SHA-256
`8c9f5f4c620a17dda952ee6cd9841ec16dc95ba64b993cafbdeaf32ab14e1aa4`.
The rebuild was generated from exact source commit
`c5f3018f686c0adf8ed212b7c71b3a3decf87ec5` and source archive SHA-256
`79e8ef5f7a168885b083dcad8c0466d79e2f05cb6e93f6ca97ed389aa830aa76`.

This audit establishes current-source recoverability, not scientific annotation quality. The
operational rebuild does not make the split independent or human gold, and no 1/5/60 model
inference had been executed when these compact artifacts were accepted.

## Promotion gates

### Before submitting any inference job

- Confirm that the CSC account is authorised for this workload and has sufficient GPU/storage
  quota. Permission to submit a job does not replace the project owner's governance or CSC data
  policy.
- Require a clean committed source archive and match its SHA-256 after transfer. The archive must
  contain a root-level `.mdmeta-source-commit` whose only value is the submitted full lowercase
  commit identifier. Reject a missing, malformed or mismatched marker before any job step runs.
- Submit CPU jobs only through `roihu_cpu` and GPU jobs only through `roihu_gpu`.
- Validate the self-committed 60-article source manifest and reject duplicate or changed article
  identifiers.
- Require all selected JATS files to reproduce their frozen SHA-256 values.
- Require the exact ungated model revision, declared licence, safetensors weights, complete
  file inventory and per-file SHA-256 verification.
- Keep machine predictions inaccessible to human annotators assigned to this corpus.

### One-article technical-gate acceptance

Proceed to five only when all of the following hold:

- Slurm state is `COMPLETED` with exit code `0:0` on one visible GH200;
- the archive SHA-256 and `.mdmeta-source-commit` both match the submitted source identity;
- exactly the first preselected manifest article was processed and every paragraph task has an
  explicit classification, with zero `schema_rejected` responses;
- the in-run determinism, frozen-JATS, offline-model, result-checksum and GPU-monitoring gates pass;
- the follow-up CPU job submitted through `roihu_cpu` produces exactly one integrated record and a
  valid SQLite/checksum result; and
- every evidence rejection or integration failure is explicit rather than silently discarded.

Batch result schema `mdmeta.llm-protocol-batch.v6` performs evidence replay at candidate and
attribute granularity after the complete response has passed response schema v3. Response v3
limits one paragraph to 16 candidate events; this exceeds the observed completed-task maximum of
11 while preventing unbounded event-array generation. A task may be
`accepted_with_evidence_rejections` only when at least one normalized event remains; every removed
candidate or attribute is bound to its candidate index and SHA-256 with a stable reason code. The
raw response and its commitment are never rewritten. Compact summaries expose aggregate reason
counts, not source text or model responses.

An unclean per-prompt completion is retained in the private result and classified as
`generation_rejected` without discarding valid peers from the same vLLM call. Its raw text (or
explicit null), commitment, finish reason and stable reason code are replayed by the CPU
integration. The default promotion gate permits at most the integer floor of 1% of tasks in this
state: this is zero for the 1- and 5-article gates and seven for the current 740-task full batch.
Any accepted large-batch generation rejection therefore remains visible as partial extraction
coverage rather than being treated as an empty model answer.

This is a technical integration gate only. It is not an extraction-quality or accuracy estimate.

### Five-article pilot acceptance

After the one-article gate passes, proceed to 60 only when all of the following hold:

- Slurm state is `COMPLETED` with exit code `0:0` on one visible GH200;
- the full result and compact summary report `status: pass` and bind the expected source archive,
  source manifest, model manifest and immutable model/tokenizer revision;
- exactly five preselected documents were processed, every generated paragraph task has an
  explicit classification, and there are zero `schema_rejected` responses;
- the in-run temperature-zero duplicate check was performed and reports identical structured
  responses;
- every JATS input matched its frozen digest and inference ran with offline model access;
- result/environment checksum verification succeeds and GPU monitoring contains usable samples;
- the CPU integration job requests five articles, writes five records, reports no unaccounted
  article loss and passes its SQLite/checksum gates; and
- any `evidence_rejected` response is retained and summarised as an explicit safe rejection. It
  must not be converted to an accepted event or silently removed to improve apparent coverage.

A pilot that finishes does not automatically pass. Resolve the cause of an integrity, schema,
OOM, environment or completeness failure and create a new auditable run rather than editing its
artifacts in place.

### Sixty-article acceptance

- Freeze the same model, prompt/schema, decoding configuration and ordered corpus used for the
  pilot; document every necessary deviation.
- Require 60 selected document identifiers and complete classification of every paragraph task.
- Require zero schema rejection, a successful in-run determinism check, valid result commitments
  and no source/model digest drift.
- Require generation rejections to remain at or below the predeclared 1% gate, report their stable
  reason counts, and mark affected article extraction completeness as partial.
- Require the downstream CPU integration to account for all 60 requested articles. A service or
  data failure must remain an explicit failure record; it cannot be removed from the denominator.
- Report elapsed GPU time, token counts, tokens/second, peak sampled memory/utilisation,
  classification counts, evidence-rejection counts, event counts and integration completeness.
- Retain source, model, job, environment and result commitments so a compact report can be checked
  without publishing model weights or full-text inputs.

## Monitoring, cancellation and resubmission

Poll `squeue` at a bounded interval while a job is pending or running, inspect the Slurm output and
atomic checkpoint, and use `sacct` after a terminal state. Monitor only jobs owned by the submitting
user. The GPU script records utilisation, memory, power and temperature once per second and writes
a checkpoint after each completed model batch.

Cancel the job with `scancel <job-id>` when there is clear evidence of an unsafe or invalid run,
including:

- the wrong account, partition, node architecture or GPU count;
- source, manifest, model-file or JATS digest mismatch;
- repeated CUDA OOM, fatal module/container error or a rapidly repeating exception;
- a checkpoint that remains unchanged while GPU utilisation stays idle long enough to exceed the
  justified pilot-based bound; or
- unexpected network/token access during the offline GPU phase, runaway storage growth, or a
  selected-article count different from the submitted plan.

Do not cancel merely because a valid job is queued. After cancellation or failure, preserve logs,
terminal Slurm accounting and the partial checkpoint; state one diagnosed cause and the exact fix
before resubmitting. Never overwrite the earlier run directory. A scheduler/node transient may be
resubmitted with the same scientific configuration but still receives a new run identifier.

## Storage, privacy and release boundary

- Keep immutable source archives under the private
  `/projappl/<project>/$USER/md-metadata-pipeline` tree.
- Run only an archive that has passed checksum/member validation and contains the root-level
  `.mdmeta-source-commit` matching the submitted commit. A plain directory copy, archive of an
  uncommitted tree or archive without the marker is not an executable source release.
- Keep model snapshots, JATS caches, full predictions, checkpoints, service caches, job logs and
  working databases under a private `/scratch/<project>/$USER/md-metadata-pipeline` run tree.
- Set `umask 077`; create user run directories with owner-only access; never copy `.git`, `.env`,
  SSH material, GitHub credentials, Hugging Face credentials, shell history or a local virtual
  environment. This model is deliberately staged without a Hugging Face token.
- Treat full JATS XML and model responses containing evidence quotes as non-public working data,
  even when the source article is open access. Honour article-specific licences and do not upload
  full text to GitHub Actions artifacts, GitHub releases or the repository.
- Do not commit model weights. The Apache-2.0 licence permits model use subject to its terms, but
  duplicating a multi-gigabyte snapshot in Git or OneDrive is unnecessary.
- Commit only reviewed compact summaries and checksums that exclude source excerpts, private
  filesystem paths, credentials and machine-specific identifiers. The shareable
  `summary.json` intentionally omits raw predictions.
- Roihu scratch is temporary, not the sole durable archive. Copy accepted compact evidence to an
  approved durable location, record the retention decision, and delete caches/weights when they
  are no longer required by the approved project.

## What each sample size can establish

| Evidence unit | Question answered | Claim that remains out of scope |
| --- | --- | --- |
| existing GH200 smoke | Can the pinned source execute correct BF16/CUDA primitives on Roihu? | no LLM, extraction or accuracy claim |
| one current article | Can the pinned model load, produce constrained output and pass the CPU integration contract? | no pilot, robustness or accuracy claim |
| five current articles | Does the real model/runtime/schema/integration path work end to end within a bounded pilot? | no robustness or accuracy estimate |
| 60 current articles | What are throughput, schema/evidence rejection, provenance and integration-completeness characteristics on the existing provisional corpus? | not independent, not human gold, not confirmatory accuracy |
| selected independent 100 after scale execution | Does the frozen pipeline scale to a new, predeclared literature cohort with complete failure accounting? | the 80 non-gold articles do not provide accuracy labels |
| future human-gold 20 | What precision, recall, F1, exact-span accuracy and agreement does the frozen extractor achieve? | confidence remains limited by 20 articles and their strata |
| future three MDDB projects | Can three preselected real projects pass topology/trajectory and MD→PDB→UniProt mapping gates? | not proof of universal MDDB coverage |

Schema conformance, deterministic decoding and exact-span reproduction are necessary integrity
checks. None is evidence that the extracted scientific statement is semantically correct.

## Independent 100 / gold 20 / future MDDB 3 study

The implemented selection and sealing protocol is tracked in
[`study/independent_100/README.md`](../study/independent_100/README.md) and
`.github/workflows/independent-100-corpus.yml`. The workflow does not run the LLM: it freezes the
new-article exclusion registry, rule-screened 80/20 plan and prediction-free human workpacks before
any Roihu inference.

The frozen independent plan uses **100 total new literature articles**, of which 20 are a
preselected, sealed human-gold subset: 80 scale articles plus 20 gold articles, not 120 and not the
current 60. It is not a current accuracy claim. The query, collection date, eligibility rules,
software strata, negative-control policy, randomisation seed, article licences and PMC/DOI
identifiers were frozen in Actions run `29457386366`. The audit excluded 93 known prior identifiers
and verified zero overlap before inference.

Select the 20 gold articles by a predeclared stratified rule before inspecting model output. Two
domain annotators independently record exact evidence spans and normalized event attributes, then
measure agreement and adjudicate every disagreement. Keep gold predictions sealed from annotators
and model developers until the model, prompt, schema, normalisation code and evaluation procedure
are frozen. Run the 80 development/scale articles and the 20 gold articles as separate manifests
and access-controlled result artifacts so the seal is operational, not merely a filename. Use the
remaining 80 articles for scale, operational completeness and qualitative error discovery; do not
tune on the sealed 20. Report accuracy only from the adjudicated gold set, with per-field counts
and article-bootstrap uncertainty, and label any later model change post-hoc.

In parallel, preselect three public MDDB projects without looking at pipeline outcome. Choose
projects that exercise different topology/trajectory or protein-mapping conditions, record asset
licences and hashes, and run the file-backed path through topology–trajectory validation,
atom/residue identity diagnostics, PDBe/SIFTS-derived mappings and UniProt positions. Report each
project independently, including failures and mapping denominators; do not replace a difficult
project unless the original violated a frozen eligibility rule.

This division maps evidence to the role more directly than sending 100 documents through a single
opaque GPU job: literature extraction scale, human-validated NLP quality, and real MD resource
interoperability are three different claims and need three different denominators.

## Application timing and safe wording

The [JR3997 vacancy](https://embl.wd103.myworkdayjobs.com/en-US/EMBL/job/Bioinformatician_JR3997)
lists a closing time of **2026-07-19 23:59 CET** and says applications may be reviewed on a rolling
basis. Do not delay the application for the unfinished scale80/gold20/MDDB3 execution. Use only
evidence that has a committed run report by submission time.

Safe progression of application wording is:

- now: “validated a reproducible one-GH200 CUDA/BF16 infrastructure gate on CSC Roihu”;
- after an accepted one-article report: “passed a pinned model-loading, constrained-decoding and
  downstream-integration technical gate,” without implying a pilot or accuracy result;
- after an accepted five-article report: “executed a pinned, schema-constrained local-model pilot
  with exact source/model provenance and downstream identifier integration”;
- after an accepted 60-article report: add the actual article/task counts, throughput,
  rejection/completeness counts and resource use, while explicitly calling the corpus provisional;
- only after blinded dual annotation and adjudication: report extraction accuracy metrics; and
- only after three accepted MDDB reports: claim multi-project file-backed MDDB interoperability.

The cover letter can explain why this architecture supports the role's literature mining,
PDBe/UniProt/SIFTS integration, FAIR provenance, scientific software and HPC responsibilities.
It must not convert a planned run, schema-pass rate or machine-only corpus into a scientific
performance result.

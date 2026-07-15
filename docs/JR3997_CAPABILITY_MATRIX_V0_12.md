# JR3997 capability matrix — version 0.12 candidate

## Executive assessment

After the live PDBe-KB run, this repository can demonstrate approximately **82%–86% of the role's
technical core**. Across the **whole JD**, including interpersonal performance, publications,
postdoctoral depth, international collaboration, training delivery and official resource ownership,
the evidence readiness is closer to **70%–75%**. These are structured portfolio estimates, not
recruiter scores and not claims that every criterion can be reduced to a percentage.

The repository cannot establish the applicant's PhD, publication record, postdoctoral experience,
interpersonal performance or direct participation in named collaborations. It also does not yet
show an official SIFTS contribution, a human-reference LLM benchmark or a deployed institutional
service.

## Scoring convention

- **Strong:** implemented, tested and supported by a dated run or cloud validation.
- **Implemented, run pending:** code and tests exist, but a live external/GPU run is still required.
- **Partial:** a material part is demonstrated, but an explicit responsibility remains missing.
- **External evidence required:** cannot be proven by repository code alone.

Percentages below are diagnostic estimates used to prioritise work; they must not be quoted as an
official job match score.

## Primary responsibilities

| Responsibility | Evidence after this upgrade | Status | Interview-safe wording | Next proof |
|---|---|---|---|---|
| Integrate MDDB with PDBe, UniProt, PDBe-KB and other resources | Real file-backed MDDB case; PDBe/UniProt validation; SIFTS-derived ranges; live two-stage PDBe-KB/FunPDBe run with 41,600 projected annotations; Neo4j projection | Strong prototype | “I implemented and live-tested the integration boundaries, including provider-level conflicts; it is not yet an institutional production feed.” | Profile diverse structures and MDDB projects; migrate reviewed common fields into the stable record/API with indexes and pagination |
| Develop and deploy AI/ML literature mining | Deterministic extractor, concrete OpenAI-compatible backend, exact-evidence validator, CPU real-model diagnostic, Roihu vLLM workflow, comparative evaluation | Implemented, GPU benchmark pending | “The model path is executable and auditable; performance remains exploratory until the frozen GPU/human-reference run.” | Qwen3.6/DeepSeek GPU benchmark, dual annotation and deployment exercise |
| Extend and maintain SIFTS for MD integration | Consumes SIFTS ranges; composes MD→PDB→UniProt; new QA for gaps, overlaps, mismatches and multi-accession chains | Partial | “I implemented a compatibility and quality layer around SIFTS outputs, not an official SIFTS code contribution.” | Run official SIFTS package/data fixtures and submit an upstream issue or PR |
| Develop software tools, APIs, workflows and documentation | Installable typed Python package, CLI tools, FastAPI, SQLite, release/recovery, GitHub Actions, Slurm/vLLM, Nextflow PoC and runbooks | Strong | “The domain logic is packaged and tested; deployment and scientific releases remain separate controlled steps.” | Institutional deployment manifest and recovery drill |
| FAIRification, standardisation and interoperability | Exact source hashes, provenance, explicit missing states, JSON Schema, release bundles, API contracts, graph export | Strong foundation / partial publication | “The records are FAIR-ready and machine-readable, but no authorised DOI/licence release is claimed.” | Controlled vocabularies, authorised licence, CITATION.cff and durable DOI release |
| Work with domain experts/resource providers | Review-oriented evidence records and explicit disputed-case workflow | External evidence required | “The software is designed for expert adjudication; I would discuss concrete mapping cases and turn decisions into tests.” | Actual co-review, issue discussion or upstream contribution |
| Training, standards and dissemination | Technical runbooks, progressive interview/tutorial explanation, reproducible examples | Partial | “I created training-ready material; public delivery or standards participation remains future evidence.” | Tutorial, talk, workshop or standards contribution |

## Essential technical criteria

| Criterion | Current evidence | Estimated technical coverage |
|---|---|---:|
| Structural biology and molecular-simulation data | Real PSF/PDB/XTC verification, chains, glycans, construct ambiguity and residue mapping | 90% |
| NLP/LLM literature mining | Exact-span extraction, real backend, failure analysis, GPU workflow and evaluation; human benchmark pending | 80% |
| FAIR data and scientific repositories | Provenance, data contracts, release/recovery and public-resource integration; citable release pending | 87% |
| Protein sequence, structure and functional annotation | PDB↔UniProt ranges plus live PDBe-KB residue annotations; official SIFTS edge-case contribution remains | 88% |
| Scientific software development | Typed Python, tests, packaging, CLI, API, databases and documented design decisions | 95% |
| Linux, Git and CI/CD | Linux workflows, Slurm, Git branches/PRs, Python matrices, security and container checks | 95% |
| Communication and problem solving | Run reports and explicit corrective decisions; interpersonal evidence must come from examples | 75% repository evidence |

## Desirable criteria

| Criterion | Evidence | Status |
|---|---|---|
| REST APIs | Typed bounded FastAPI service and stable problem details | Strong |
| Containers | Non-root, read-only production-candidate image and Compose smoke tests | Strong prototype |
| Graph databases / Neo4j | Deterministic Neo4j bulk-import CSV projection with relationship semantics | Implemented |
| Workflow systems / Nextflow | Minimal DSL2 workflow orchestrating extraction and comparison against an existing model endpoint | Proof of concept |
| Data visualisation and analysis | Comparison Markdown/JSON, confusion and uncertainty outputs; no rich interactive dashboard | Partial |
| Biological data lifecycle | Acquisition, validation, release, recovery and deprecation boundaries documented | Partial–strong |
| Scientific presentation | Progressive 30-second, 2-minute and deep-dive material | Repository evidence only |
| International interdisciplinary teamwork | Cannot be established by code | External evidence required |

## Before/after estimate

| Stage | Repository-demonstrable technical core | Main limitation |
|---|---:|---|
| Before production/LLM upgrades | approximately 70%–75% | No concrete model backend, direct PDBe-KB path or production controls |
| Current version 0.12 candidate after live PDBe-KB | approximately 82%–86% | GPU/human LLM benchmark pending; SIFTS not upstream; only one file-backed MDDB project |
| After live GPU + human benchmark + official SIFTS contribution | potentially 88%–92% | Multi-project production deployment and external collaboration still cannot be simulated by code |

## What the Roihu result can change

A successful Roihu run will demonstrate operational GPU inference, exact model revision provenance,
end-to-end strict validation, latency/token accounting and a reproducible deterministic/LLM/hybrid
comparison. It cannot by itself establish accuracy unless the reference is independently annotated
and adjudicated.

The strongest positive result would be:

- higher hybrid phase-aware attribute F1 than the deterministic baseline;
- a paired article-bootstrap interval that supports a genuine improvement;
- acceptable invalid-output and abstention rates;
- documented gains for difficult fields such as phase association without unacceptable precision
  loss;
- reproducible latency and resource requirements.

A negative result is also useful: if the interval does not support improvement, the project should
retain deterministic extraction as the primary system and use the LLM only for candidate discovery
or expert prioritisation.

## Prioritised remaining work

### P0 — needed for the strongest application claim

1. Complete independent dual annotation and adjudication on a locked test set.
2. Run Qwen3.6 and one exact DeepSeek revision on Roihu with identical frozen inputs.
3. Profile PDBe-KB on a stratified structure sample; quantify provider field variability and design a
   versioned indexed API/storage migration for reviewed common fields.
4. Run official SIFTS compatibility fixtures for insertion codes, missing residues, isoforms,
   engineered mutations, chimeras and homomer ambiguity.
5. Expand from one file-backed MDDB project to several heterogeneous projects and test incremental
   refresh/upstream drift.
6. Publish an authorised citable release with licence, creators, publisher, CITATION.cff and DOI.

### P1 — differentiators

1. Load the graph projection into a disposable Neo4j instance and record representative Cypher
   queries and result counts.
2. Run the Nextflow PoC and compare its provenance/operability with the direct Slurm runner.
3. Add residue-coverage and protocol-error visualisations that expose missingness and uncertainty.
4. Submit a small external issue, fixture or documentation improvement to SIFTS/PDBe tooling.
5. Turn the progressive explanation into a short tutorial or presentation delivered to an audience.

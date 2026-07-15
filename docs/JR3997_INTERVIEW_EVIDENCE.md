# JR3997 interview evidence: progressive explanation

## One-sentence conclusion

I built an evidence-first molecular-dynamics metadata pipeline that links literature and public MD
assets to PDBe, UniProt, SIFTS-derived residue mappings and PDBe-KB annotations, while treating LLM
outputs and external-service responses as auditable candidates rather than database truth.

## 30-second version

The problem is that MD simulations, structures, protein annotations and methods in papers are stored
in different formats and use different identifiers. My project extracts protocol metadata with exact
source evidence, validates PDB and UniProt identifiers, composes MD-residue to PDB to UniProt
mappings, and exposes the resulting records through tested Python, SQLite and FastAPI components. I
also added a real open-weight LLM path, a Roihu GPU benchmark, PDBe-KB enrichment and SIFTS quality
checks. The key design choice is fail-closed validation: uncertain or malformed information remains
`unresolved` instead of becoming a confident biological fact.

## Two-minute version

### Problem

A researcher may have an MDDB topology and trajectory, a starting PDB structure, a UniProt sequence,
functional annotations in PDBe-KB and protocol details embedded in prose. These are useful together,
but identifiers, residue numbering, missing residues, constructs and literature wording make naive
joins unsafe.

### Approach

1. Parse local or permitted JATS paragraphs and retain source hashes.
2. Extract explicit protocol events and exact evidence spans.
3. Validate PDB and UniProt identifiers through audited, cached public-service calls.
4. consume SIFTS-derived PDB-chain to UniProt ranges and compose them with verified MD-to-PDB
   correspondences when real files are available.
5. Retrieve PDBe-KB/FunPDBe annotations as a conservative sidecar; unsupported provider-specific
   shapes are retained as hashes or unresolved payloads rather than guessed.
6. Store integrated records transactionally, expose a bounded typed API, and export graph-shaped data
   for Neo4j when relationship queries are useful.
7. Compare deterministic, LLM and validated-hybrid extraction on the same frozen corpus with exact,
   phase-aware and paired-bootstrap metrics.

### Evidence

- The file-backed MDDB case verified PSF, PDB and XTC assets and created thousands of MD-to-PDB and
  MD-to-PDB-to-UniProt residue correspondences.
- The 60-article integration completed end to end with explicit validation and mapping states.
- A real Qwen CPU smoke run exposed an important evidence error: the model understood a replicate
  count but changed the source text from `three` to `3`; the exact-source validator rejected that
  transformation.
- CI tests Python 3.11/3.12, packaging, contracts, security and a hardened container path.

### Boundary

This is a production-candidate research prototype, not an official extension of the SIFTS codebase,
not a deployed PDBe service and not a human-reference LLM accuracy claim. The next evidence step is a
frozen Roihu GPU run and independently adjudicated benchmark.

## Technical deep dive

### Why evidence is separate from enrichment

A paper is evidence for what the authors reported. PDBe, UniProt and PDBe-KB can validate or enrich
that report, but they must not overwrite the literature statement. Every literature fact therefore
retains a quote, character offsets and context hash. External responses retain endpoint, state,
response hash, retry history and cache status.

### Why network failure is not a biological conflict

A timeout means the service was unavailable. It does not mean a PDB entry or mapping is false. The
pipeline distinguishes:

- `validated`: a successful service response satisfies the expected contract;
- `conflict`: a successful response provides evidence that the identifier/mapping is absent;
- `unresolved`: no reliable scientific decision is possible because of network or payload failure.

### Why SIFTS mapping needs a QA layer

Integer range equality is not sufficient for every structure. The QA report identifies incomplete or
reversed ranges, length mismatch, duplicates, overlapping segments and chains mapped to more than one
accession. These are review signals, not automatic errors. Insertion codes, engineered mutations,
isoforms and chimeras ultimately require residue-level comparison with the official SIFTS data model.

### Why PDBe-KB is initially a sidecar

PDBe-KB integrates heterogeneous provider annotations. Adding unknown provider fields directly to the
stable database schema before observing real payload diversity would create brittle contracts. The
adapter therefore projects only explicit provider, type, label, chain and residue-range fields,
retains response hashes, and records a valid-but-unprojected state. After live payload profiling and
domain review, the stable IntegratedMDRecord and API can be migrated deliberately.

### Why SQLite and Neo4j both appear

SQLite is the authoritative compact release store because it provides transactions, foreign keys,
backup and straightforward deployment. Neo4j CSV is an analytical projection for questions such as:

- which articles, structures and MD assets connect to a UniProt accession;
- which PDB chains carry annotations from several providers;
- where residue mappings and functional annotations overlap.

The graph export is derived and reproducible; it does not become a second source of truth.

### Why deterministic, LLM and hybrid are compared together

A model can improve recall but also hallucinate or normalise evidence. The benchmark therefore reports:

- strict event precision, recall and F1;
- phase-aware attribute precision, recall and F1;
- duration-plus-phase F1 and confusion;
- article-bootstrap confidence intervals;
- paired F1 difference against the deterministic baseline;
- latency, tokens, finish reasons and zero-event documents.

The hybrid is a union only after each LLM event has passed the same exact-evidence validator. A higher
point estimate is insufficient; the paired interval and error groups determine whether the change is
scientifically useful.

## STAR stories

### 1. LLM evidence normalisation

**Situation:** A real Qwen run extracted six correct semantic values from an MD methods sentence.

**Task:** Determine whether the result was safe to store as provenance-linked metadata.

**Action:** Compared each raw value with the exact source substring instead of checking semantic
equivalence alone.

**Result:** The model changed `three` to `3`. The validator rejected the exact-evidence claim, proving
why deterministic validation is necessary even when the apparent answer is correct.

### 2. CPU throughput was the bottleneck

**Situation:** Full structured positive outputs repeatedly exceeded 180 seconds on a GitHub CPU
runner, while a negative response completed.

**Task:** Separate model inability, JSON Schema complexity and hardware throughput.

**Action:** Ran nested-schema, flat-schema, unconstrained and minimal-output controls while recording
latency and token counts.

**Result:** Even unconstrained long output timed out, whereas a 64-token result took about 142 seconds.
I rejected the CPU backend for production and created a revision-locked Roihu vLLM path instead of
misreporting timeouts as model errors.

### 3. Real MD-to-protein mapping

**Situation:** Public MD files used prepared-system residues, glycans and repeated chains that did not
map trivially to the source structure.

**Task:** Create a defensible MD-residue to PDB to UniProt mapping.

**Action:** Verified file hashes and atom/residue counts, aligned protein sequences, retained construct
variants and chain ambiguity, then composed only length-consistent SIFTS segments.

**Result:** Produced thousands of residue correspondences while preserving unmapped and ambiguous
states instead of forcing total coverage.

### 4. Stable schema versus rapidly changing upstream annotations

**Situation:** PDBe-KB annotations come from multiple providers with potentially different shapes.

**Task:** Add direct functional-annotation evidence without destabilising the production-candidate
record contract.

**Action:** Built a conservative audited sidecar that projects a small explicit common core and hashes
the source record; unknown shapes remain valid-but-unprojected.

**Result:** The project now demonstrates direct PDBe-KB integration while retaining a controlled path
to a future schema migration after live profiling and expert review.

## Likely interview questions

### How would you handle missing data?

First distinguish absence, inapplicability, service failure and unsupported representation. I would
retain explicit states, analyse whether missingness is systematic, avoid imputing identifiers or
residue mappings, and use imputation only for downstream statistical models where assumptions and
sensitivity analyses are documented.

### How would you validate an LLM extractor?

Freeze corpus, model revision, prompt, JSON Schema, code commit and decoding settings before releasing
the locked test labels. Use independent dual annotation and adjudication; score strict events,
phase-aware attributes and evidence validity; report bootstrap uncertainty, invalid-output rate,
latency and error categories. The deterministic extractor remains the baseline.

### How would you extend SIFTS?

Start with compatibility tests against official SIFTS outputs for insertion codes, missing residues,
isoforms, engineered mutations, chimeras and ambiguous chains. Propose the smallest data-model or
mapping change, add regression fixtures, discuss it with SIFTS maintainers and contribute upstream
rather than maintaining a private incompatible fork.

### How would you work with domain experts?

Bring concrete disputed records rather than abstract schema questions. For each case, show source
text, structure chain, UniProt range, mapping decision and uncertainty; agree controlled terms and
acceptance rules; record decisions as tests and versioned documentation. The repository architecture
supports this workflow, but actual collaboration must be demonstrated through team examples.

## Claims that are supported

- Built a cloud-tested scientific integration prototype linking literature, MD assets, PDBe,
  UniProt and SIFTS-derived mappings.
- Implemented a direct conservative PDBe-KB annotation adapter.
- Implemented a real OpenAI-compatible open-weight LLM client with exact-evidence rejection.
- Designed a revision-locked Roihu GPU benchmark and deterministic/LLM/hybrid evaluation.
- Implemented typed APIs, data contracts, transactional storage, release/recovery controls and
  CI/security gates.

## Claims that are not yet supported

- Extended or maintained the official SIFTS production codebase.
- Deployed a production service at PDBe or MDDB.
- Demonstrated Qwen3.6-27B or DeepSeek accuracy on an independent human gold standard.
- Published a citable FAIR dataset with an authorised DOI and licence.
- Collaborated directly with ELIXIR, Instruct-ERIC, EU-OPENSCREEN or the named resource teams through
  this repository alone.

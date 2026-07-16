# JR3997 end-to-end MD metadata integration

## Purpose

This workflow turns an evidence-bearing molecular-dynamics article into a record that can be
searched by article, PDB entry, UniProt accession and SIFTS-derived residue range. It implements
the core software path relevant to EMBL-EBI JR3997 while keeping literature statements,
external-database enrichment and file-derived provenance separate.

The golden case is Woo et al. (2020), DOI `10.1021/acs.jpcb.0c04553`. The repository stores a
small curated evidence fixture, not the publisher's full text. It tests the explicit starting
structures `6VSB` and `6VXX`, the glycosylated system and viral-membrane context.

## Six-step code path

### 1. Read the article and extract explicit metadata

`src/mdmeta/integration.py` provides:

- `parse_jats_paragraphs`: converts JATS sections and paragraphs into stable `Paragraph` objects;
- `extract_article_metadata`: records title, DOI, source URI and full-source SHA-256;
- `extract_literature_facts`: extracts explicit PDB identifiers and supported system/protocol
  fields with exact paragraph-relative offsets;
- `protocol_paragraphs` and the existing `extract_protocol_events`: recover phase-aware MD events.

Every `LiteratureFact` has an exact evidence quote, offsets and context hash. No PDBe or UniProt
value is written as a literature fact.

### 2. Validate PDB identifiers with PDBe

`integrate_article` calls `IdentifierValidator.validate_pdb` for every extracted starting PDB ID.
The existing client supplies bounded retries, response caching, request-attempt logs and canonical
response hashes.

A timeout or temporary service failure is `unresolved`. A successful service response showing that
the identifier is absent is `conflict`. These states are not interchangeable.

### 3. Discover and validate UniProt accessions

`discover_uniprot_mappings` queries the PDBe UniProt mapping endpoint only after the PDB entry has
validated. It discovers accessions from the response instead of guessing them from article text.
Each discovered accession is then checked through `IdentifierValidator.validate_uniprot`.

For the golden case, the live acceptance gate requires both `6VSB` and `6VXX` to map to `P0DTC2`.

### 4. Preserve SIFTS-derived residue mappings

The PDBe mapping response is converted to `MappingSegment` objects containing PDB ID, chain,
PDB residue range, UniProt accession and UniProt residue range. The record reports
`pdb_to_uniprot_only` unless a separately verified MD-to-PDB correspondence is supplied.

SIFTS does not by itself prove how a prepared MD topology was renumbered. The pipeline therefore
never invents an `MD residue -> PDB residue` mapping.

### 5. Validate MD assets and workflow provenance

`build_provenance` reads a manifest of starting structures, prepared coordinates, topology,
trajectory and workflow steps. A local asset marked `verified_local` must exist and pass SHA-256
verification. External references and unavailable files remain explicitly labelled.

The golden example declares the PDB entries as external references and the topology/trajectory as
unavailable. Its MD-to-PDB mapping is therefore `not_computable`, which is a scientifically useful
result rather than a failed attempt to fabricate residue correspondence.

### 6. Store records and expose an API

`SQLiteRecordStore` writes a transactional SQLite database with normalized article, literature
fact, validation, residue-mapping and MD-asset tables while retaining the complete integrated JSON
record. `create_app` exposes:

- `GET /health`;
- `GET /records/{document_id}`;
- `GET /search?pdb_id=6VSB`;
- `GET /search?uniprot_accession=P0DTC2`.

## Golden-case acceptance gates

Offline tests use deterministic mocked PDBe/UniProt responses and must prove:

1. `6VSB` and `6VXX` are extracted from exact evidence spans;
2. both PDB identifiers validate;
3. mapping discovery returns `P0DTC2` and residue segments;
4. literature facts are not overwritten by external enrichment;
5. network failure remains `unresolved`;
6. verified local assets fail closed on missing files or SHA mismatch;
7. SQLite and REST queries return the integrated record.

The separate live job must prove that current PDBe, UniProt and mapping endpoints satisfy the same
identifier expectations. Full external payloads are kept in the hashed cache artifact; integrated
records store compact audit metadata by default.

## Run the golden case

```bash
python scripts/run_integrated_case.py \
  --xml examples/woo_2020/article_fixture.xml \
  --document-id WOO2020 \
  --source-uri https://doi.org/10.1021/acs.jpcb.0c04553 \
  --manifest examples/woo_2020/provenance_manifest.json \
  --output results/golden/woo_2020.json \
  --database results/golden/records.sqlite \
  --cache-dir results/golden/cache \
  --expect-pdb 6VSB --expect-pdb 6VXX \
  --expect-uniprot P0DTC2
```

## Extension to the frozen 60-article set

`study/integration_60/source_manifest.json` fixes the 30/10/20 article order and contains the
SHA-256 of every JATS snapshot used in the earlier screening run, together with the source workflow
and artifact commitments. The batch runner downloads current JATS XML and refuses to integrate an
article if its source hash has changed.

The current path now points to the accepted 2026-07-15 operational rebuild, which replaced two
drifted positions by the first two currently valid original reserves. It has not yet produced a
model-backed 1/5/60 result. The dated 2026-07-10 integration result remains bound only to
`study/integration_60/source_manifest_original.json`; do not use that historical result as evidence
for the rebuilt corpus.

```bash
python scripts/run_integrated_60.py \
  --source-manifest study/integration_60/source_manifest.json \
  --output-dir results/integrated_60 \
  --database results/integrated_60/records.sqlite \
  --cache-dir results/integrated_60/cache
```

For each of 60 articles the workflow writes one compact JSON record, a SQLite database and an
aggregate coverage report. Articles without explicit PDB identifiers remain valid literature and
protocol records with `not_applicable` external-identifier status. Articles without public MD files
remain `not_provided`; they do not receive synthetic provenance.

## Scientific reporting boundary

The integration run measures pipeline coverage and validation states, not extraction accuracy.
The existing 60-article AI-consensus evaluation remains exploratory rather than a human gold
standard. Live database responses are enrichment evidence, not reference annotations, and they
never replace article-derived values.

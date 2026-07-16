# Neo4j-ready graph export

Version 0.12 can export one checkpointed schema-v2 SQLite snapshot as deterministic Neo4j
bulk-import CSV files without adding a second live persistence dependency:

```bash
mdmeta-export-graph export \
  --database /srv/mdmeta/releases/current/records.sqlite \
  --output-dir /srv/mdmeta/graph-candidate
```

The output contains `nodes.csv`, `relationships.csv` and `graph-manifest.json`. The manifest binds
the source database SHA-256, schema version, article/report counts, graph counts and both CSV file
hashes into one graph commitment. Export refuses a database with WAL/SHM sidecars and excludes MD
asset local paths, evidence quotes, raw external API payloads and protein sequences.

Verify the transferred export, optionally rebinding it to the copied database:

```bash
mdmeta-export-graph verify \
  --output-dir /srv/mdmeta/graph-candidate \
  --database /srv/mdmeta/releases/current/records.sqlite
```

Verification rejects unexpected files, symlinks, checksum or count drift, duplicate identifiers,
invalid property JSON and relationships whose endpoints are absent.

## Graph semantics

Node labels are `Article`, `PDB`, `UniProt`, `ProtocolEvent`, `MDAsset`, `PDBeKBAnnotation` and
`AnnotationPartner`. Relationship types are:

- `MENTIONS_STRUCTURE`: exact-span literature evidence names a PDB entry;
- `HAS_PROTOCOL_EVENT`: an article owns an extracted, evidence-bound protocol event;
- `USES_STRUCTURE`: an integrated article record contains a residue mapping for a PDB structure;
- `SIFTS_MAPS_TO`: a PDB chain/range maps to a UniProt range for one source article;
- `HAS_MD_ASSET`: an article declares or verifies an MD input asset;
- `HAS_PDBEKB_ANNOTATION`: a UniProt accession has a compact PDBe-KB annotation group;
- `LINKS_STRUCTURE`: a PDBe-KB annotation group refers to a PDB entry; and
- `HAS_ANNOTATION_PARTNER`: a UniProt enrichment identifies a PDBe-KB annotation provider.

Node and relationship identifiers are content-derived and rows are sorted, so the same immutable
database produces byte-identical CSVs. `properties_json` retains nested provenance without
inventing a graph-native ontology. The top-level identifier, name, state and source URI columns
support initial queries and indexes.

## Example queries

```cypher
MATCH (article:Article)-[:USES_STRUCTURE]->(pdb:PDB)
MATCH (pdb)-[mapping:SIFTS_MAPS_TO]->(protein:UniProt)
RETURN article.identifier, pdb.identifier, protein.identifier,
       mapping.source_document_id, mapping.properties_json
ORDER BY article.identifier, pdb.identifier;
```

```cypher
MATCH (protein:UniProt)-[:HAS_PDBEKB_ANNOTATION]->(annotation:PDBeKBAnnotation)
OPTIONAL MATCH (annotation)-[:LINKS_STRUCTURE]->(pdb:PDB)
RETURN protein.identifier, annotation.name, collect(DISTINCT pdb.identifier)
ORDER BY protein.identifier, annotation.name;
```

This export demonstrates a defined graph projection and supports evaluation in Neo4j. It does not
claim that Neo4j is required for production. SQLite remains the authoritative immutable snapshot
until real graph-query workload, operations and consistency requirements justify a second store.

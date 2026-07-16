# Official PDBe-SIFTS compatibility

The project pins its compatibility check to the official
[PDBeurope/SIFTS](https://github.com/PDBeurope/SIFTS) release `v1.0.4`, exact commit
`155a4258536078ff0251644f154e895b7da6c492`. That package is the open-source, locally deployable
SIFTS pipeline; this repository does not vendor it or reimplement its alignment/scoring algorithm.

The dedicated GitHub Actions workflow checks out that immutable source and uses the upstream
`1cbs_seg.csv.gz` and `1cbs_res.csv.gz` fixtures. It verifies their recorded SHA-256 values, parses
all 26 segment columns and 24 residue columns through this project's strict adapter, executes the
upstream `get_unp_segments` and `get_unpres_mapping` readers, and compares counts plus the projected
1CBS→P29373 mapping. A compact content-committed report is uploaded; no sequence or coordinate data
is retained in it.

The adapter deliberately preserves distinctions relevant to SIFTS work:

- author and structural chain identifiers;
- author residue numbers and insertion codes;
- PDB SEQRES and UniProt coordinate systems;
- canonical versus isoform accessions;
- best versus alternative mappings;
- observed versus unobserved residues;
- conflicts, modifications and chimeric segments; and
- explicit row, column, entry-ID and boolean-encoding validation.

Only best, accession-bound segments are projected into the existing compact `MappingSegment`
model. The full parsed object remains available for compatibility diagnostics, so alternative,
chimera, insertion-code and unobserved-residue states are not silently converted into a simple
one-to-one range.

This is a pinned interface/fixture compatibility result. It is not evidence that the full
PDBe-SIFTS sequence-search and local-alignment pipeline has been run at PDB scale, and it is not an
upstream contribution. A future contribution should begin with an issue or regression case agreed
with PDBe maintainers rather than an unsolicited change to scientific mapping behaviour.

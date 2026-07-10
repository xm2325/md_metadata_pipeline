# Woo et al. 2020 golden integration case

This directory is a **curated evidence fixture**, not a redistribution of the publisher's full text.
It contains only the article identity and the two short claims needed to test the software path:

1. explicit starting structures `6VSB` and `6VXX`;
2. a fully glycosylated spike model in a viral membrane.

The live workflow validates both PDB identifiers, discovers their UniProt mappings through the
PDBe mapping endpoint, validates the returned UniProt accessions, records SIFTS-derived residue
segments, and keeps MD topology/trajectory availability explicitly unresolved rather than inventing
an MD-to-PDB residue map.

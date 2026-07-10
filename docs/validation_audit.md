# Identifier and mapping validation audit

The validation layer checks extracted identifiers after literature extraction. It does not create literature facts from database responses.

## PDBe

A PDB identifier is checked through the PDBe entry-summary service. A successful response containing the requested entry is `validated`; a successful response without it is `invalid`; a service failure is `unresolved`.

## UniProt

A UniProt accession is checked against the returned primary accession. Equality is `validated`; a different returned accession is `conflict`; a service failure is `unresolved`.

## SIFTS-derived mapping

For each PDB identifier, PDBe mapping data are parsed into PDB-chain and UniProt residue ranges. Extracted PDB-UniProt pairs are then compared with returned mappings.

- pair present: `validated`;
- mapping response received but pair absent: `conflict`;
- mapping request failed: `unresolved`.

## Audit output

`mdlit validation-audit` reports:

- counts by status, validator, and field;
- PDB and UniProt mapping coverage;
- protocol-event validation counts;
- total unresolved or conflicting events.

Response hashes and source URLs are stored when available so that a validation decision can be traced to the retrieved payload.

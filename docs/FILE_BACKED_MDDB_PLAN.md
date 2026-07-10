# File-backed MDDB mapping

The first public case is MDDB project `MCV1900193.2`, the second closed-state full-length SARS-CoV-2 Spike trajectory used by the official MDDB API tutorials.

The implementation must pass the following gates before merge:

1. retrieve and hash the project metadata and public file descriptors;
2. download an MDDB structure topology and a bounded authentic trajectory frame subset;
3. report whether a force-field topology and original workflow/configuration files are actually public;
4. parse topology and trajectory independently;
5. require matching atom counts and a non-zero frame count;
6. report atom, residue, protein-residue, chain and frame counts;
7. record simulation program/version, force field, timestep, ensemble and the exact retrieval commands;
8. hash every downloaded file and every public JSON response;
9. align MD protein residues to the stated starting PDB structure without assuming residue numbering;
10. compose the verified MD-to-PDB correspondence with SIFTS PDB-to-UniProt mappings;
11. report coverage, mismatches, insertions, deletions and ambiguous chain assignments;
12. fail closed when a file changes, an atom count disagrees, or mapping evidence is insufficient.

A structure PDB may act as the coordinate topology required to read the trajectory, but it must not be described as a force-field topology such as PSF, TPR, PRMTOP or TOP unless that file is actually exposed by MDDB.

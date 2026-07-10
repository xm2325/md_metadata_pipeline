# Confirmatory benchmark protocol (locked before annotation)

The confirmatory study uses 60 open-access articles selected from a saved Europe PMC query and a frozen candidate manifest. Sampling is stratified by reported simulation engine. The split is 30 development, 10 validation, and 20 untouched test articles. Article identifiers and source hashes are fixed before reference annotation.

Two annotators independently record exact evidence spans, normalized values, units, protocol event type, PDB identifiers, UniProt accessions, chain identifiers, and PDB–UniProt relations. Agreement is reported before adjudication. Database validation is run only after extraction and cannot populate reference labels.

The primary endpoint is micro F1 on the 20-article untouched test set for event-linked facts. Secondary endpoints are field-level F1, event exact match, duration–phase relation F1, article exact match, calibration, validation-state counts, and article-bootstrap 95% confidence intervals. Frozen model changes after test release are prohibited. Any later model is labelled post-hoc.

This repository provides the schema and execution code. It does not claim completion of dual annotation until two independent exports and an adjudicated set are committed with hashes.

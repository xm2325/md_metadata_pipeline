# External validation semantics

`validated` means a successful authoritative response supports the requested identifier or relation. `conflict` requires a successful service response that contradicts the extracted identifier or relation. `unresolved` covers timeouts, rate limits, server errors, missing mapping responses, and other cases where a biological contradiction cannot be established. `not_applicable` is used when no identifier was extracted.

The pipeline stores endpoint, retrieval time, HTTP status, response hash, query, decision reason, and optional response payload. External values never overwrite literature extraction. Enrichment, inference, normalization, and validation remain separate records.

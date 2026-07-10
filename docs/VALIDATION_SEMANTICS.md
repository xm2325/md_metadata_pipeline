# External validation semantics and audit provenance

External validation is a post-extraction check. It does not create literature-derived facts, replace extracted values, or fill reference annotations.

## Validation states

| State | Meaning |
|---|---|
| `validated` | A successful authoritative response supports the requested identifier or relation. |
| `conflict` | A successful response contradicts the requested identifier or relation. |
| `unresolved` | The service did not provide enough reliable information to decide, including timeouts, rate limits, server errors, and unavailable mapping responses. |
| `not_applicable` | No relevant identifier or relation was extracted. |

A network error is never converted to `conflict`. A successful HTTP 404 for a requested identifier is treated as `conflict`, while a non-success server or rate-limit response that does not establish absence remains `unresolved`.

## Request algorithm

For each endpoint, the validator applies the following sequence:

1. Check the local response cache and verify the stored canonical JSON hash.
2. If no valid cache entry exists, issue the request.
3. Retry network errors and HTTP 429, 500, 502, 503, and 504 responses up to the configured limit.
4. Use `Retry-After` when it is numeric, capped by `max_retry_after_seconds`; otherwise use exponential backoff.
5. Store every attempt as a `RequestAttempt` containing attempt number, outcome, HTTP status or error type, and retry delay.
6. Hash the canonical JSON response and store the endpoint, status, response hash, and payload in the resulting `ValidationRecord`.

The number of attempts excludes cache hits. A cache hit has `attempts=0`, `cache_hit=true`, and a request log entry with outcome `cache`.

## Response cache

The optional file cache is intended for public PDBe and UniProt responses used in reproducible research runs.

- Cache keys are SHA-256 hashes of full endpoint URLs.
- Only successful HTTP 200 JSON responses are cached.
- Cache contents include endpoint, status, canonical response hash, and payload.
- A cache entry is rejected when the endpoint or response hash does not match.
- Writes use a temporary file followed by an atomic rename.

The current cache has no time-to-live or release-snapshot policy. A confirmatory study must record whether cached or newly retrieved responses were used and should archive the validation bundle or service release information needed for later reconstruction.

## PDB and UniProt identifiers

PDB identifiers are checked using the PDBe entry-summary endpoint. UniProt accessions are checked against the returned primary accession. Each decision retains the endpoint, retrieval time, status, response hash, request log, reason, and optional payload.

## SIFTS-derived mapping

PDB-to-UniProt relations are checked using the PDBe UniProt mapping endpoint. Returned mapping segments retain:

- PDB identifier;
- UniProt accession;
- chain identifier;
- PDB residue start and end;
- UniProt residue start and end.

A returned accession and requested chain produce `validated`. A successful mapping response that omits the requested relation or chain produces `conflict`. A failed or non-success mapping request produces `unresolved`.

## Aggregate audit

Validation records can be summarized without modifying the original records:

```bash
python scripts/summarize_validation.py \
  --records results/validation_records.json \
  --output results/validation_summary.json
```

The summary reports state counts, identifier-type counts, reason counts, cache hits, total network attempts, mapping-segment counts, and the combined unresolved-or-conflict count.

## Current evidence boundary

Offline tests use fixed mocked responses to verify state transitions, retries, cache behavior, and residue-range parsing. They are software tests, not a current live audit of PDBe, UniProt, or SIFTS services. A batch live audit remains a separate research task and must report retrieval dates, service failures, rate limiting, and response hashes.

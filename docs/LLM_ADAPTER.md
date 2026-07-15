# Schema-constrained model adapter

The model adapter is provider-independent. It does not contain credentials, call a commercial API, or report model accuracy. A backend implements one method:

```python
complete(prompt: str, json_schema: dict) -> dict
```

The returned dictionary is parsed with a strict Pydantic schema. Unknown fields are rejected.

## Acceptance sequence

A proposed event enters the pipeline only after its phase, quote and at least one attribute pass:

1. The paragraph identifier exists in the supplied input.
2. Character offsets fall within the paragraph.
3. The quoted evidence is identical to the source substring at those offsets.
4. Every numeric attribute includes an exact `raw_text` expression copied from the quote.
5. Python parses the number and unit from `raw_text` and verifies that they agree with the model-proposed value and unit.
6. Python performs unit conversion to ps, K, bar, or fs.
7. Ensemble and replicate expressions must occur in the quote; restraint text must also contain an explicit restraint/constraint cue, so arbitrary substrings such as `N` cannot become metadata.
8. Unsupported attributes are rejected individually and recorded with stable reason codes. They are never copied into the normalized event.
9. The event must retain at least one evidence-valid protocol attribute after filtering.
10. A stable event identifier is derived from the document, evidence span, event type, and normalized attributes.

The original structured response and its hash remain unchanged. A candidate with a supported phase and at least one valid attribute may survive conservative removal of unsupported attributes; the private result records candidate indices, candidate hashes, repairs and rejection reason codes. A candidate with no valid attribute is rejected. One rejected candidate does not erase an independently valid candidate from the same schema-valid response. A structurally invalid response is still rejected as a whole.

Batch result schema v4 also isolates an unclean completion to its own task. A token-limited,
missing, or non-strict-JSON response is retained privately as raw text (or an explicit null), bound
to a SHA-256 commitment, and classified as `generation_rejected`; valid peer responses in the
same inference batch continue through validation. Compact summaries contain only aggregate stable
reason codes. The default run gate permits generation rejection for at most 1% of tasks (integer
floor), so the 1- and 5-article gates still require zero while a large batch can preserve a small,
explicit partial-coverage tail.

An incorrect `event_type_raw_text` can be repaired only when it is an exact substring of the quote and the quote contains exactly one non-conflicting explicit cue for the already-declared phase. The phase label is never changed automatically. Exact offset repair remains limited to one unique byte-for-byte quote occurrence.

## Supported raw quantities

- duration: fs, ps, ns, us, µs, μs, ms;
- temperature: K, kelvin, °C, Celsius;
- pressure: bar, atm;
- timestep: fs, ps;
- replicate counts: integers or English words one through ten.

The adapter currently treats one exact quote as the evidence unit for one event. Cross-paragraph relation extraction is not accepted. Batch result schema v4 distinguishes fully accepted tasks from `accepted_with_evidence_rejections` and `generation_rejected`, and publishes only aggregate reason counts in compact summaries.

## Prompt rule

The generated prompt instructs the model to extract only explicit MD protocol events, avoid outside knowledge, return exact paragraph-relative offsets, and return an empty list when no supported event is present. It also forbids phase-only or duplicate events, requires at least one supported protocol attribute per event, and requires every supported attribute explicitly stated in the chosen quote to be populated instead of silently omitted.

## Evaluation rule

Model performance must be measured on a locked annotated set using the existing event evaluator. Unit tests with a fake backend demonstrate software behavior only. They do not provide an LLM precision, recall, or F1 result.

Any provider-specific backend, prompt change, model identifier, decoding setting, or schema version must be recorded in the experiment manifest before opening a locked test set.

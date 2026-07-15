# Schema-constrained model adapter

The model adapter is provider-independent. It does not contain credentials, call a commercial API, or report model accuracy. A backend implements one method:

```python
complete(prompt: str, json_schema: dict) -> dict
```

The returned dictionary is parsed with a strict Pydantic schema. Unknown fields are rejected.

## Acceptance sequence

A proposed event enters the pipeline only after all checks pass:

1. The paragraph identifier exists in the supplied input.
2. Character offsets fall within the paragraph.
3. The quoted evidence is identical to the source substring at those offsets.
4. Every numeric attribute includes an exact `raw_text` expression copied from the quote.
5. Python parses the number and unit from `raw_text` and verifies that they agree with the model-proposed value and unit.
6. Python performs unit conversion to ps, K, bar, or fs.
7. Ensemble, restraint text, and replicate expressions must occur in the quote.
8. The event must contain at least one protocol attribute.
9. A stable event identifier is derived from the document, evidence span, event type, and normalized attributes.

A failure raises `EvidenceIntegrityError`; the candidate is not written as a `ProtocolEvent`.

## Supported raw quantities

- duration: fs, ps, ns, us, µs, μs, ms;
- temperature: K, kelvin, °C, Celsius;
- pressure: bar, atm;
- timestep: fs, ps;
- replicate counts: integers or English words one through ten.

The adapter currently treats one exact quote as the evidence unit for one event. Cross-paragraph relation extraction is not accepted.

## Prompt rule

The generated prompt instructs the model to extract only explicit MD protocol events, avoid outside knowledge, return exact paragraph-relative offsets, and return an empty list when no supported event is present. It also forbids phase-only or duplicate events, requires at least one supported protocol attribute per event, and requires every supported attribute explicitly stated in the chosen quote to be populated instead of silently omitted.

## Evaluation rule

Model performance must be measured on a locked annotated set using the existing event evaluator. Unit tests with a fake backend demonstrate software behavior only. They do not provide an LLM precision, recall, or F1 result.

Any provider-specific backend, prompt change, model identifier, decoding setting, or schema version must be recorded in the experiment manifest before opening a locked test set.

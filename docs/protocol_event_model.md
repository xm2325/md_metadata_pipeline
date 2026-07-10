# Protocol-event model

A flat record such as `temperature=300 K` cannot identify whether the value belongs to heating, equilibration, production, or an experimental assay. The event model keeps phase and local evidence with each group of conditions.

## Event phases

Supported phases are:

```text
initialization
minimisation
heating
equilibration
production
sampling_interval
analysis_window
reported_result
unspecified
```

`unspecified` is a valid uncertainty state. It must not be converted to production only because production is common.

## Event construction

1. Duration facts form event anchors when available.
2. Conditions in the same paragraph are linked when their evidence spans are within a fixed distance and their phases do not conflict.
3. A paragraph with conditions but no duration forms a partial event.
4. Values are not copied across unrelated paragraphs.
5. Limited section-level propagation is allowed only for unresolved temperature, pressure, ensemble, time step, or replicate facts when the section contains an explicit production event and the source paragraph contains no heating, equilibration, or initialization language.
6. Every event retains the contributing fact identifiers and evidence spans.

## Completeness

- `complete`: at least four protocol attributes and an explicit phase;
- `partial`: fewer fields or no duration;
- `ambiguous`: multiple duration anchors with no resolved phase.

Completeness is not a confidence score. A complete event may still contain a database conflict or extraction error.

## Evaluation

Exact event evaluation compares full event signatures. Attribute evaluation converts each event to phase-aware attributes such as:

```text
(document, production, duration_value, 500)
(document, production, ensemble, NPT)
(document, production, temperature_k, 300)
```

Both are needed: exact event scoring is strict, while attribute scoring shows whether individual conditions were recovered even when event grouping differs.

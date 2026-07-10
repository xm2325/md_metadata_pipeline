# MD Metadata Pipeline

Evidence-linked extraction and validation for molecular-dynamics literature, designed for the EMBL-EBI JR3997 problem setting.

## Current research evidence

The frozen-v2 independent held-out result remains the primary model result: 15 articles, 165 reference facts, precision 0.844, recall 0.695, and F1 0.763. The 120-article unlabelled audit produced 1,204 evidence-linked facts with no execution failure; it does not provide an accuracy estimate.

Version 0.3 adds two next-stage components without changing the frozen-v2 result:

1. A phase-aware protocol-event schema that links duration, temperature, pressure, ensemble, timestep, restraint text, and replicate count within a local evidence unit.
2. A PDBe, UniProt, and SIFTS-derived validation client with explicit `validated`, `conflict`, `unresolved`, and `not_applicable` states.

External databases do not fill reference labels and never overwrite extracted literature values. Network failure is not treated as biological conflict.

## Run

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=mdmeta --cov-branch
```

See `docs/CONFIRMATORY_BENCHMARK.md` and `docs/VALIDATION_SEMANTICS.md` for the locked next-stage study design and validation rules.

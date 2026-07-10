# Real-study release boundary

The repository publishes study code and aggregate results, but not full article XML, article-level predictions, exact quotations, or single-reviewer annotation files. Those materials remain in the controlled research workspace and are subject to source licences and annotation governance.

`run_protocol_event_pilot.py` reproduces the aggregate development diagnostic when the omitted `review_text/` and `annotations/` directories are supplied locally. `prepare_confirmatory_60.py` queries Europe PMC metadata and creates a deterministic 30/10/20 split; it requires network access.

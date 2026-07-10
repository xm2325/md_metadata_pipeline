# Confirmatory 60-article workspace

The corpus must not be locked until `prior_article_ids.txt` contains every article used in earlier development and independent held-out studies. The preparation command requires at least 30 unique prior article IDs by default.

Generated Europe PMC responses, candidate manifests, and the locked 30/10/20 plan belong under `generated/` and should be stored as workflow artifacts. Full article XML is not committed here.

Current blocker: 15 original development IDs are recorded; the 15 earlier held-out IDs still need to be recovered and added. This blocker is deliberate. It prevents test-set reuse.

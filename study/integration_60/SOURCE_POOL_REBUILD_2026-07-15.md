# Full source-pool audit and deterministic rebuild — 2026-07-15

## Scope and evidence boundary

This note records the accepted current-source availability audit and the deterministic operational rebuild of the frozen 60-article pool. The audit verifies source bytes and availability; it is not scientific or human annotation. The rebuild does not make the existing splits independent, gold-standard, or suitable for an accuracy claim.

The authoritative machine-readable records are:

- `source_pool_audit.json` — complete audit, file SHA-256 `ab4f6fc8a799aec35c5fdb177f67e82fba1482935ac1df9931a80eb820340eca`, internal audit SHA-256 `62d9c0063a47c0b86a52723a2262c72116f5902c0997c32ee49cf9e5ff57f5ea`;
- `source_manifest.json` — accepted operational manifest, file SHA-256 `2c0e0275b2b3303607ccb30e9632994d86a2d71367dcc3cd73581e59d1bbd74e`, internal manifest SHA-256 `b73387925f866162c42863aa7957c759c1404b5ed9229c8d6b57ed4707a2bdfe`;
- `source_pool_rebuild_report.json` — rebuild report, file SHA-256 `8c9f5f4c620a17dda952ee6cd9841ec16dc95ba64b993cafbdeaf32ab14e1aa4`, internal report SHA-256 `1bae366076d02f606238424796957576d56d15e5727d4ee37ef5f324bec5a491`;
- `source_manifest_superseded_185650.json` — preserved superseded one-row remediation, file SHA-256 `404a43cd1297b8803f75d4a50d356887adbecdd7cdc0b29d6d1fe196e1cb6a23`.

No full text, model output, private filesystem path, username, or compute-node name is included in these accepted records.

## Accepted full-pool audit

Audit job `185845` completed against source commit `874225952dd675d08de2ee43a6333f185ad64152` and source archive SHA-256 `9c7257075f61225859dd56a6086646274d5d09523e87976ac949a7a409f5a1b5`.

- Audited records: `78` — all `60` originally selected articles plus all `18` ordered eligible reserves.
- Originally selected articles: `58` exact current-byte matches and `2` requiring replacement because their current payloads drifted.
- Reserves: `17` currently valid; this was sufficient for the two required replacements.
- Cache classification: `75` matching files and `3` diagnostic files.
- Unresolved records: `0`; audit status: `complete`.
- Original split counts were `30` development, `10` validation, and `20` locked test.

The audit used the original manifest as its authority: internal SHA-256 `03f4bc46caf60071db8dc9fca63e0ddf9a7734ac3232a87737d6d32f7630a7a6`, file SHA-256 `252174ea1f6936287b71cde78787e310564b81736148d19eeb6b325f21e15b2d`.

## Deterministic rebuild

Rebuild job `187089` ran from source commit `c5f3018f686c0adf8ed212b7c71b3a3decf87ec5` and immutable source archive SHA-256 `79e8ef5f7a168885b083dcad8c0466d79e2f05cb6e93f6ca97ed389aa830aa76`. It applied policy `all_drifted_positions_to_first_n_currently_valid_original_reserves.v1`, using only the accepted audit and original reserve order. Decision-key SHA-256: `64faec325f62728594cba726910561356e713fef5737a68a5afdb2631c0b56e6`.

The two replacements were:

1. Position `1`, development: `PMC6316748` (frozen SHA-256 `cdbfd10f7e85a4042ebda7317b06cf963061f05e00d99168c03a5ed7e03a337d`, `105780` bytes; observed current SHA-256 `51d20c7e8b35720e9150d2118d274cf2e5048a64fdaf7905552210530a87d52a`, `102369` bytes) was replaced by original reserve rank `1`, `PMC6994855` (accepted SHA-256 `169ced75f7adf4ed9ab18bf28ec08ecd8ab76414dd81367ae9f277702ddc5a4d`, `87028` bytes).
2. Position `42`, locked test: `PMC6423238` (frozen SHA-256 `84f16b7c412c5f233fca4fe46346bf0ae8e21cea5b0f14df0fac9f9bbce60c30`, `103808` bytes; observed current SHA-256 `726228d1c9f293b5703b01cbe8f7b0e806bf384dbadc841a91f02349bdbf5b37`, `112203` bytes) was replaced by original reserve rank `2`, `PMC7603383` (accepted SHA-256 `8684fec5432ca305f1c3960fca5ae1432f4bcc6b67086669f294344c14eccd8c`, `115199` bytes).

The resulting manifest contains `60` unique document IDs: `58` unchanged and `2` replaced. Positions and split membership were preserved, leaving `30` development, `10` validation, and `20` locked-test articles. The rebuild report status is `pass`; no model output was used to select replacements.

A separate CPU validation job (`187035`) verified this exact rebuild source commit and archive and completed `88` tests with `0` failures, `0` errors, and `0` skips. Its result-file SHA-256 is `3ce4368415fc14d262899f1f1d73b730e5a36beac77bb52152109a808f8c87b4`.

## Current study state

The accepted manifest status is `provisional_operational_multi_rebuild_not_accuracy`. Model-backed inference gates for `1`, `5`, and `60` articles have **not yet been executed** against this rebuilt pool. Consequently, this acceptance establishes source integrity and deterministic lineage only; it does not establish extraction accuracy, biological validity, throughput, or readiness for production use.

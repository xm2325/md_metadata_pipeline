# Protocol-event development diagnostic

This run uses the existing 15-article, single-reviewer reference set. It is a development diagnostic, not an independent test and not the planned 60-article dual-annotation benchmark.

| System | Phase-aware fact precision | Recall | F1 | Duration+phase F1 | Events | Events with explicit phase |
|---|---:|---:|---:|---:|---:|---:|
| v1 baseline | 0.389 | 0.256 | 0.309 | 0.000 | 33 | 0 |
| v2 protocol-aware | 0.665 | 0.665 | 0.665 | 0.459 | 54 | 50 |

## Interpretation

The result measures exact normalized values together with protocol phase. It is intentionally stricter than phase-free field scoring. The event count is an engineering output; it is not an accuracy metric because the current reference set contains fact annotations rather than independently adjudicated event graphs.

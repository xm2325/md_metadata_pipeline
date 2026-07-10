# AI-annotated exploratory evaluation

Date: 2026-07-10

## Scope

This is an **AI-annotated exploratory evaluation**, not a human gold-standard benchmark. Sixty open-access articles were reviewed using a blinded packet containing article metadata, abstracts, and 698 protocol-relevant JATS paragraphs. The packet contained no frozen machine predictions and no complete article XML.

Three blind AI annotation passes were combined, followed by AI adjudication. The semantic reference was frozen before the machine-prediction artifact was opened. A later JATS text-node spacing correction changed paragraph offsets but not semantic event decisions; all evidence spans were re-anchored successfully.

- Articles reviewed: 60
- Articles judged biomolecular-MD eligible by the AI review: 58
- Articles judged outside scope: 2 (`PMC6316748`, `PMC7345908`)
- AI-consensus reference events: 215
- Frozen machine events: 281
- Reference commitment: `66ff6f6031bbd899c7e4d33daec2ec8fe8bbead4f6cfe790aad1cbb462a2ffc8`
- Prediction commitment: `ab3c3f1e9c34a29055dc91871c632b96fd28df4c15e8dcf1c0ce2cdfdfc77e8c`
- Blind packet commitment: `330fb8685574c7e56672424604ded3804e63b8a1718cf4919320be41170ce305`

## Main results

| Evaluation level | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Strict complete event | 105 | 176 | 110 | 0.374 | 0.488 | **0.423** |
| Phase-aware attributes | 247 | 286 | 98 | 0.463 | 0.716 | **0.563** |
| Duration + phase | 162 | 119 | 53 | 0.577 | 0.753 | **0.653** |

The article-bootstrap 95% interval for phase-aware attribute F1 was **0.497–0.621** using 2,000 article-level bootstrap samples and seed 3997.

On the 58 articles judged eligible by the AI review, phase-aware attribute F1 was **0.571**, with a 95% article-bootstrap interval of **0.502–0.629**.

## Field-level F1

| Attribute | F1 |
|---|---:|
| duration | 0.653 |
| temperature | 0.535 |
| pressure | 0.522 |
| ensemble | 0.490 |
| replicates | 0.261 |
| time step | 0.080 |
| restraints | 0.000 |

The most important engineering defect is time-step handling. Small integration time steps were sometimes emitted as event durations. Other recurring errors were excess `unknown` events, sampling intervals interpreted as simulated duration, analysis windows confused with production trajectories, and incorrect linking of conditions to a nearby duration in dense multi-stage paragraphs.

## Reference uncertainty

The three blind AI passes contained 298, 191 and 330 event candidates. Their pairwise duration-plus-phase F1 values were approximately 0.54–0.60. This disagreement indicates substantial reference uncertainty and is the main reason the machine score must remain exploratory.

## Reporting boundary

The existing development, validation and locked-test labels remain provisional corpus placeholders. All 60 articles were used to create the AI reference, so none of the split-specific results is an independent test estimate.

A defensible statement is:

> In a blinded, AI-annotated exploratory evaluation over 60 open-access articles, the frozen deterministic extractor achieved phase-aware attribute precision 0.463, recall 0.716 and F1 0.563; duration-plus-phase F1 was 0.653. The reference is an AI consensus rather than a human gold standard, and human adjudication remains required.

Do not describe these results as confirmatory, human-validated or gold-standard performance.

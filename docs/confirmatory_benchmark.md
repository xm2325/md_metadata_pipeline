# Confirmatory 60-article benchmark

## Objective

Estimate field-level and phase-aware event extraction performance on a locked set of open-access MD articles that were not used to modify extraction rules.

## Corpus construction

The metadata search query, complete response, response SHA-256, selection seed, exclusion list, candidate manifest, and locked split are saved before annotation starts.

Eligibility requires:

1. a PMC identifier and available JATS full text;
2. an article reporting at least one performed molecular-dynamics simulation;
3. enough protocol text to assess at least one target field;
4. no membership in the earlier 15-article development pilot.

The target split is:

- 30 development articles;
- 10 validation articles;
- 20 locked-test articles.

Sampling cycles across detected simulation-software families before filling remaining positions. Unknown software is retained as its own stratum rather than discarded.

## Annotation

Two annotators independently label exact evidence spans. Each fact contains:

- document and annotator identifiers;
- field and normalized value;
- unit;
- protocol phase;
- paragraph identifier and character offsets;
- exact quote;
- optional note.

Annotators must not inspect system predictions while producing first-pass labels.

Agreement is reported as exact set agreement over normalized fact, unit, phase, paragraph, and character span. Field-level agreement is reported separately. All differences are retained in an adjudication file; no label is silently selected from one annotator.

## Locked evaluation

Extraction code, controlled vocabularies, retrieval threshold, normalization rules, and model prompts must be frozen before the 20-article locked test is opened. Any later modification creates a new post-hoc system and cannot replace the original locked result.

Primary metrics:

1. micro precision, recall, and F1 over normalized facts;
2. micro precision, recall, and F1 over normalized fact plus phase;
3. duration-plus-phase F1;
4. event-attribute F1;
5. exact event F1;
6. article-level bootstrap 95% confidence intervals.

Secondary metrics include exact evidence-span accuracy, identifier validity, abstention, database-validation conflict rate, and complete-record rate.

## Stopping and reporting rules

- Do not remove hard articles after annotation begins.
- Replace an article only for a documented eligibility failure, never because system performance is poor.
- Report every locked article, including pipeline failures.
- Treat a failure to produce a record as zero recall for that article.
- Report missing annotation agreement and unresolved adjudication items explicitly.
- Do not merge post-hoc results into the independent result table.

## Current status

The software for metadata search, deterministic split creation, double-annotation comparison, adjudication templates, event evaluation, and database audit is implemented. The full 60-article dual-annotation study has not yet been completed. A second human annotator is required before confirmatory metrics can be reported.

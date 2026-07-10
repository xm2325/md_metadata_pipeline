from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import MDRecord


def validation_audit(record: MDRecord) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    by_validator: dict[str, Counter[str]] = defaultdict(Counter)
    by_field: dict[str, Counter[str]] = defaultdict(Counter)

    for fact in record.facts:
        if not fact.validation:
            status_counts["not_checked"] += 1
            by_field[fact.field_name]["not_checked"] += 1
        for event in fact.validation:
            status_counts[event.status] += 1
            by_validator[event.validator][event.status] += 1
            by_field[fact.field_name][event.status] += 1
    for event in record.record_validation:
        status_counts[event.status] += 1
        by_validator[event.validator][event.status] += 1
    for event in record.protocol_events:
        for validation in event.validation:
            status_counts[validation.status] += 1
            by_validator[validation.validator][validation.status] += 1

    pdb_ids = {str(f.normalized_value).upper() for f in record.facts_for("pdb_id")}
    mapped_pdbs = {mapping.pdb_id.upper() for mapping in record.mappings}
    uniprots = {str(f.normalized_value).upper() for f in record.facts_for("uniprot_accession")}
    mapped_uniprots = {mapping.uniprot_accession.upper() for mapping in record.mappings}

    return {
        "document_id": record.article.document_id,
        "fact_count": len(record.facts),
        "protocol_event_count": len(record.protocol_events),
        "mapping_count": len(record.mappings),
        "status_counts": dict(sorted(status_counts.items())),
        "by_validator": {
            key: dict(sorted(value.items())) for key, value in sorted(by_validator.items())
        },
        "by_field": {key: dict(sorted(value.items())) for key, value in sorted(by_field.items())},
        "identifier_coverage": {
            "pdb_extracted": len(pdb_ids),
            "pdb_with_mapping": len(pdb_ids & mapped_pdbs),
            "uniprot_extracted": len(uniprots),
            "uniprot_with_mapping": len(uniprots & mapped_uniprots),
        },
        "unresolved_or_conflict": status_counts["unresolved"] + status_counts["conflict"],
    }

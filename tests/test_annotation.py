import json

from mdmeta.annotation import AnnotationFact, compare_annotators, write_adjudication_template
from mdmeta.models import EventType


def _fact(annotator: str, *, start: int = 5, value: float = 300) -> AnnotationFact:
    return AnnotationFact(
        annotation_id=f"{annotator}-1",
        document_id="PMC1",
        annotator_id=annotator,
        field_name="temperature_k",
        normalized_value=value,
        unit="K",
        event_type=EventType.PRODUCTION,
        paragraph_id="p1",
        start_char=start,
        end_char=start + 5,
        quote="300 K",
    )


def test_reports_semantic_and_exact_agreement_separately(tmp_path) -> None:
    result = compare_annotators([_fact("a")], [_fact("b", start=9)])
    assert result["semantic_set_agreement"] == 1.0
    assert result["exact_set_agreement"] == 0.0
    assert result["exact_only_a_count"] == 1
    assert result["exact_only_b_count"] == 1

    output = tmp_path / "adjudication.json"
    write_adjudication_template(result, output)
    payload = json.loads(output.read_text())
    assert payload["status"] == "not_adjudicated"
    assert len(payload["items"]) == 2
    assert all(item["decision"] == "pending" for item in payload["items"])

from mdlit.annotation import AnnotationFact, compare_annotators
from mdlit.benchmark import CandidateArticle, create_benchmark_plan


def _annotation(annotator: str, value: int = 300) -> AnnotationFact:
    return AnnotationFact(
        annotation_id=f"{annotator}-1",
        document_id="DOC",
        annotator_id=annotator,
        field_name="temperature",
        normalized_value=value,
        unit="K",
        phase="production",
        paragraph_id="p1",
        start_char=10,
        end_char=15,
        quote="300 K",
    )


def test_annotation_comparison_keeps_disagreements() -> None:
    result = compare_annotators([_annotation("a")], [_annotation("b", 310)])
    assert result["agreed_count"] == 0
    assert result["only_a_count"] == 1
    assert result["only_b_count"] == 1
    assert result["set_agreement"] == 0


def test_benchmark_plan_is_stable_and_excludes_previous_articles() -> None:
    candidates = [
        CandidateArticle(
            document_id=f"PMC{i:05d}",
            title=f"Article {i}",
            software_family=["gromacs", "amber", "namd", "openmm"][i % 4],
            source_uri=f"https://example.org/{i}",
        )
        for i in range(75)
    ]
    excluded = {"PMC00000", "PMC00001"}
    first = create_benchmark_plan(candidates, excluded_document_ids=excluded)
    second = create_benchmark_plan(candidates, excluded_document_ids=excluded)
    assert first.plan_sha256 == second.plan_sha256
    selected = {
        item.document_id for item in first.development + first.validation + first.locked_test
    }
    assert len(selected) == 60
    assert not selected & excluded
    assert len(first.development) == 30
    assert len(first.validation) == 10
    assert len(first.locked_test) == 20

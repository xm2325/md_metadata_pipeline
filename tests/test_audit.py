from mdlit.audit import validation_audit
from mdlit.pipeline import run_pipeline


def test_validation_audit_reports_protocol_events(tmp_path) -> None:
    record = run_pipeline(
        "data/demo/article.xml",
        "DOC",
        "synthetic://doc",
        tmp_path,
    )
    audit = validation_audit(record)
    assert audit["fact_count"] == 12
    assert audit["protocol_event_count"] >= 1
    assert "status_counts" in audit

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from mdlit.pipeline import run_pipeline


def test_pipeline_writes_audit_outputs(tmp_path: Path) -> None:
    record = run_pipeline(
        "data/demo/article.xml",
        "PMC-SYNTHETIC-JR3997",
        "synthetic://demo",
        tmp_path,
    )
    assert len(record.facts) == 12
    for name in [
        "record.json",
        "protocol_events.json",
        "mddb_partial.json",
        "audit.sqlite",
        "report.html",
    ]:
        assert (tmp_path / name).exists()
    partial = json.loads((tmp_path / "mddb_partial.json").read_text())
    assert partial["TEMP"] == 310
    with closing(sqlite3.connect(tmp_path / "audit.sqlite")) as connection:
        count = connection.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM evidence WHERE fact_id IS NOT NULL"
        ).fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM protocol_event").fetchone()[0]
    assert count == 12
    assert evidence_count == 12
    assert event_count == len(record.protocol_events)

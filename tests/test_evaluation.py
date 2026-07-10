import json
from pathlib import Path

from mdlit.evaluation import evaluate
from mdlit.pipeline import run_pipeline


def test_synthetic_regression_evaluation(tmp_path: Path) -> None:
    record = run_pipeline("data/demo/article.xml", "DOC", "synthetic://doc", tmp_path)
    gold = json.loads(Path("data/demo/gold.json").read_text())
    result = evaluate(record, gold)
    assert result["evaluation_scope"] == "synthetic_software_regression_only"
    assert result["f1"] == 1.0
    assert result["evidence_offset_integrity"] is True

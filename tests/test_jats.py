from pathlib import Path

from mdlit.jats import parse_jats


def test_parse_demo_jats() -> None:
    article = parse_jats(Path("data/demo/article.xml"))
    assert article.title == "Synthetic MD protocol article for software regression testing"
    assert article.doi == "10.0000/synthetic.jr3997"
    assert article.pmcid == "PMCSYNTHETIC-JR3997"
    assert len(article.paragraphs) == 3
    assert article.paragraphs[0].section == "Molecular dynamics methods"
    assert article.paragraphs[0].paragraph_id == "methods-p1"

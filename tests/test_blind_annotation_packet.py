import hashlib
from pathlib import Path

from mdmeta.benchmark import canonical_sha256
from scripts.build_blind_annotation_packet import build_packet

XML = b'''<article article-type="research-article"><front><article-meta><title-group><article-title>Protein MD study</article-title></title-group><abstract><p>We simulated a protein.</p></abstract></article-meta></front><body><sec><title>Introduction</title><p>Background only.</p></sec><sec><title>Molecular dynamics methods</title><p id="m1">The system was equilibrated for 2 ns at 300 K.</p></sec></body></article>'''


def test_packet_is_blinded_and_hash_locked(tmp_path: Path) -> None:
    digest = hashlib.sha256(XML).hexdigest()
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "PMC1.xml").write_bytes(XML)
    screen = {
        "records": [{"document_id": "PMC1", "full_text_sha256": digest}],
    }
    plan = {
        "study_status": "provisional_temporal_isolation_machine_screened",
        "plan_sha256": "a" * 64,
        "screen_sha256": canonical_sha256(screen),
        "development": [
            {
                "document_id": "PMC1",
                "title": "Protein MD study",
                "doi": "10.1/example",
                "year": 2020,
                "source_uri": "https://europepmc.org/articles/PMC1",
            }
        ],
        "validation": [],
        "locked_test": [],
    }
    packet = build_packet(plan, screen, cache)
    assert packet["article_count"] == 1
    assert packet["contains_machine_predictions"] is False
    assert packet["contains_full_article_xml"] is False
    article = packet["articles"][0]
    assert article["abstract"] == "We simulated a protein."
    assert article["method_paragraph_count"] == 1
    assert article["method_sections"][0]["paragraphs"][0]["paragraph_id"] == "m1"
    assert "Background only" not in str(packet)
    assert "prediction" not in str(article).lower()
    assert len(packet["packet_sha256"]) == 64

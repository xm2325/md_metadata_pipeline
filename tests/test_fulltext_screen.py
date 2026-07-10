from scripts.screen_selected_fulltext import screen_plan, screen_xml

STRONG_XML = b'''<article article-type="research-article"><front><article-meta><title-group><article-title>Test MD paper</article-title></title-group></article-meta></front><body><sec><title>Molecular dynamics methods</title><p>We performed molecular dynamics simulations of a protein with GROMACS using a force field and TIP3P water. Production simulation was 100 ns in the NPT ensemble at 300 K and 1 bar with a time step of 2 fs.</p></sec></body></article>'''
WEAK_XML = b'''<article article-type="research-article"><front><article-meta><title-group><article-title>Review</article-title></title-group></article-meta></front><body><sec><title>Introduction</title><p>Molecular dynamics may be useful.</p></sec></body></article>'''


def test_screen_xml_reports_hash_and_biomolecular_protocol_signal() -> None:
    result = screen_xml("PMC1", STRONG_XML, "development")
    assert result["machine_screen_status"] == "strong_biomolecular_protocol_signal"
    assert result["engine_mentions"] == ["gromacs"]
    assert result["biomolecular_domain_signal"] is True
    assert result["machine_eligible_for_annotation"] is True
    assert len(result["full_text_sha256"]) == 64
    assert result["method_section_titles"] == ["Molecular dynamics methods"]
    assert "Production simulation was 100 ns" not in str(result)


def test_screen_plan_keeps_scope_explicit() -> None:
    plan = {
        "study_id": "test",
        "study_status": "provisional_temporal_isolation",
        "plan_sha256": "a" * 64,
        "development": [{"document_id": "PMC1"}],
        "validation": [{"document_id": "PMC2"}],
        "locked_test": [],
    }

    def fetcher(identifier: str) -> bytes:
        return STRONG_XML if identifier == "PMC1" else WEAK_XML

    result = screen_plan(plan, fetcher)
    assert result["screened_articles"] == 2
    assert result["failure_count"] == 0
    assert result["status_counts"] == {
        "non_biomolecular_or_weak_signal": 1,
        "strong_biomolecular_protocol_signal": 1,
    }
    assert result["machine_eligible_count"] == 1
    assert all(
        record["screening_scope"] == "machine_triage_not_human_eligibility"
        for record in result["records"]
    )

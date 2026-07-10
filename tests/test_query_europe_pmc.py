from scripts.query_europe_pmc import _article, software_family


def test_software_family_and_article_conversion() -> None:
    assert software_family("Simulated with GROMACS and OpenMM") == "gromacs+openmm"
    article = _article(
        {
            "pmcid": "PMC123",
            "title": "An MD simulation",
            "abstractText": "GROMACS was used",
            "pubYear": "2025",
            "doi": "10.1/test",
            "license": "CC BY",
        }
    )
    assert article is not None
    assert article["document_id"] == "PMC123"
    assert article["year"] == 2025
    assert article["software_family"] == "gromacs"

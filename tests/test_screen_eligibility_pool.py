import httpx

from mdmeta.benchmark import CandidateArticle
from mdmeta.screening_pool import create_screening_pool
from scripts.screen_eligibility_pool import screen_pool

STRONG_XML = b'''<article article-type="research-article"><front><article-meta><title-group><article-title>Test MD paper</article-title></title-group></article-meta></front><body><sec><title>Molecular dynamics methods</title><p>We performed molecular dynamics simulations of the protein-ligand complex with GROMACS using a force field and TIP3P water. Production simulation was 100 ns in the NPT ensemble at 300 K and 1 bar with a time step of 2 fs.</p></sec></body></article>'''


def test_screen_pool_keeps_order_and_pool_hash():
    candidates = [
        CandidateArticle(
            document_id=f"PMC{i:06d}",
            title=f"Article {i}",
            source_uri=f"https://example.org/{i}",
            year=2018,
            software_family="gromacs",
        )
        for i in range(60)
    ]
    pool = create_screening_pool(candidates, pool_size=60)

    def handler(request):
        return httpx.Response(200, content=STRONG_XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = screen_pool(pool.model_dump(mode="json"), client, delay=0)
    assert result["pool_sha256"] == pool.pool_sha256
    assert result["screened_articles"] == 60
    assert result["failure_count"] == 0
    assert [row["pool_position"] for row in result["records"]] == list(range(1, 61))
    assert {row["split"] for row in result["records"]} == {"unassigned"}

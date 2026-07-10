import pytest

from mdlit.clients import PDBeClient, UniProtClient


@pytest.mark.live
def test_pdbe_and_uniprot_live_contracts() -> None:
    summary, _, _ = PDBeClient().entry_summary("1ubq")
    assert "1ubq" in summary
    entry, _, _ = UniProtClient().entry("P0CG47")
    assert entry["primaryAccession"] == "P0CG47"

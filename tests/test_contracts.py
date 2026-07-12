from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdmeta.contracts import CONTRACTS, export_contracts


ROOT = Path(__file__).parents[1]


def test_committed_contract_schemas_are_current_and_strict() -> None:
    outputs = export_contracts(ROOT / "schemas", check=True)

    assert {path.name for path in outputs} == set(CONTRACTS)
    integrated = json.loads(
        (ROOT / "schemas" / "integrated-md-record-v1.schema.json").read_text()
    )
    assert integrated["additionalProperties"] is False
    assert integrated["properties"]["schema_version"]["const"] == (
        "integrated-md-record-v1"
    )
    assert integrated["$defs"]["Evidence"]["additionalProperties"] is False
    release = json.loads(
        (ROOT / "schemas" / "mdmeta-dataset-release-v1.schema.json").read_text()
    )
    database = release["$defs"]["DatabaseContract"]
    assert database["additionalProperties"] is False
    assert database["properties"]["schema_version"]["const"] == 1


def test_contract_check_detects_drift(tmp_path: Path) -> None:
    export_contracts(tmp_path)
    changed = tmp_path / "integrated-md-record-v1.schema.json"
    changed.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="out of date"):
        export_contracts(tmp_path, check=True)


def test_contract_check_rejects_stale_schema_inventory(tmp_path: Path) -> None:
    export_contracts(tmp_path)
    (tmp_path / "retired-v0.schema.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inventory mismatch"):
        export_contracts(tmp_path, check=True)

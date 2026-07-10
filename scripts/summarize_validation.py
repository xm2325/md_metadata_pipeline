from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.models import ValidationRecord
from mdmeta.validation import summarize_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize validation records without changing them.")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.records.read_text(encoding="utf-8"))
    rows = payload["records"] if isinstance(payload, dict) else payload
    records = [ValidationRecord.model_validate(row) for row in rows]
    result = summarize_validation(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.annotation import compare_annotators, load_annotations, write_adjudication_template


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two independent exact-span annotation exports.")
    parser.add_argument("--annotator-a", type=Path, required=True)
    parser.add_argument("--annotator-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudication-template", type=Path, required=True)
    args = parser.parse_args()

    result = compare_annotators(
        load_annotations(args.annotator_a),
        load_annotations(args.annotator_b),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.adjudication_template.parent.mkdir(parents=True, exist_ok=True)
    write_adjudication_template(result, args.adjudication_template)
    summary = {key: value for key, value in result.items() if key != "disagreements"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

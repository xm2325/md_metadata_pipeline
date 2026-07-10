from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.eligibility import (
    compare_eligibility_reviews,
    create_adjudication_template,
    load_eligibility_reviews,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two independent eligibility reviews.")
    parser.add_argument("--review-a", type=Path, required=True)
    parser.add_argument("--review-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudication-template", type=Path, required=True)
    args = parser.parse_args()
    result = compare_eligibility_reviews(
        load_eligibility_reviews(args.review_a),
        load_eligibility_reviews(args.review_b),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    adjudication = create_adjudication_template(result)
    args.adjudication_template.parent.mkdir(parents=True, exist_ok=True)
    args.adjudication_template.write_text(json.dumps(adjudication, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "comparable_count",
                    "agreement_count",
                    "disagreement_count",
                    "decision_agreement",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

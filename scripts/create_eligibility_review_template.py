from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.eligibility import create_blind_review_template


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a split-blind human eligibility template.")
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-seed", type=int, default=7041)
    args = parser.parse_args()
    result = create_blind_review_template(
        json.loads(args.pool.read_text(encoding="utf-8")),
        json.loads(args.screen.read_text(encoding="utf-8")),
        review_seed=args.review_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "template_sha256": result["template_sha256"],
                "articles": len(result["articles"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.eligibility import load_adjudicated_eligibility, lock_after_eligibility


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select the first 60 adjudicated eligible articles, then assign 30/10/20."
    )
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--adjudicated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-seed", type=int, default=9041)
    args = parser.parse_args()
    result = lock_after_eligibility(
        json.loads(args.pool.read_text(encoding="utf-8")),
        load_adjudicated_eligibility(args.adjudicated),
        split_seed=args.split_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_sha256": result["plan_sha256"],
                "reviewed_prefix_count": result["reviewed_prefix_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

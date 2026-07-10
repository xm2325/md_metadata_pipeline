from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.benchmark import load_candidate_manifest
from mdmeta.screening_pool import create_screening_pool


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a deterministic candidate pool before human eligibility review."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--excluded-ids", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=3997)
    parser.add_argument("--pool-size", type=int, default=120)
    parser.add_argument("--publication-year-min", type=int)
    parser.add_argument("--publication-year-max", type=int)
    parser.add_argument("--require-known-year", action="store_true")
    args = parser.parse_args()

    excluded: set[str] = set()
    if args.excluded_ids is not None:
        excluded = {
            line.strip().upper()
            for line in args.excluded_ids.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    pool = create_screening_pool(
        load_candidate_manifest(args.candidates),
        excluded_document_ids=excluded,
        seed=args.seed,
        pool_size=args.pool_size,
        publication_year_min=args.publication_year_min,
        publication_year_max=args.publication_year_max,
        require_known_year=args.require_known_year,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(pool.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"pool_sha256": pool.pool_sha256, "pool_size": pool.pool_size}, indent=2))


if __name__ == "__main__":
    main()

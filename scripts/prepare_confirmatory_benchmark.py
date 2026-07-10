from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.benchmark import create_benchmark_plan, load_candidate_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic 30/10/20 benchmark plan.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--excluded-ids", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=3997)
    parser.add_argument("--minimum-excluded", type=int, default=30)
    args = parser.parse_args()

    excluded: set[str] = set()
    if args.excluded_ids is not None:
        excluded = {
            line.strip().upper()
            for line in args.excluded_ids.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    if len(excluded) < args.minimum_excluded:
        raise SystemExit(
            f"exclusion registry has {len(excluded)} unique IDs; "
            f"at least {args.minimum_excluded} are required before locking the corpus"
        )
    plan = create_benchmark_plan(
        load_candidate_manifest(args.candidates),
        excluded_document_ids=excluded,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"plan_sha256": plan.plan_sha256, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()

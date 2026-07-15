#!/usr/bin/env python3
"""Stage and cryptographically bind one ungated Hugging Face model snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.model_snapshot import stage_model_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-license", required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = stage_model_snapshot(
        repo_id=args.repo_id,
        revision=args.revision,
        expected_license=args.expected_license,
        snapshot_dir=args.snapshot_dir,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "repo_id",
                    "revision",
                    "license",
                    "file_count",
                    "total_size_bytes",
                    "weight_file_count",
                    "weight_size_bytes",
                    "manifest_sha256",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

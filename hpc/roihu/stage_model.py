#!/usr/bin/env python3
"""Stage and cryptographically bind one ungated Hugging Face model snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.model_snapshot import load_and_verify_model_snapshot, stage_model_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-license", required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="verify and reuse a previously staged immutable snapshot instead of downloading",
    )
    args = parser.parse_args()
    if args.verify_existing:
        result = load_and_verify_model_snapshot(args.snapshot_dir, args.manifest)
        identity_matches = (
            result.get("repo_id") == args.repo_id
            and result.get("revision") == args.revision
            and result.get("tokenizer_revision") == args.revision
            and isinstance(result.get("license"), str)
            and result["license"].casefold() == args.expected_license.casefold()
        )
        if not identity_matches:
            raise SystemExit(
                "existing model snapshot identity or licence differs from the request"
            )
    else:
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

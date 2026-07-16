from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mdmeta.model_protocol_freeze import (
    authorize_gold20_prediction,
    freeze_model_protocol,
    sha256_file,
)


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the scale-tested protocol before authorizing gold20 inference."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze-protocol")
    freeze.add_argument("--scale-manifest", type=Path, required=True)
    freeze.add_argument("--scale-result", type=Path, required=True)
    freeze.add_argument("--scale-integration-result", type=Path, required=True)
    freeze.add_argument("--model-manifest", type=Path, required=True)
    freeze.add_argument("--source-root", type=Path, required=True)
    freeze.add_argument("--source-archive", type=Path, required=True)
    freeze.add_argument("--gpu-environment", type=Path, required=True)
    freeze.add_argument("--gpu-summary", type=Path, required=True)
    freeze.add_argument("--integration-environment", type=Path, required=True)
    freeze.add_argument("--integration-database", type=Path, required=True)
    freeze.add_argument("--frozen-at-utc", required=True)
    freeze.add_argument("--operator-run-id", required=True)
    freeze.add_argument("--output", type=Path, required=True)

    authorize = subparsers.add_parser("authorize-gold20")
    authorize.add_argument("--plan", type=Path, required=True)
    authorize.add_argument("--screen", type=Path, required=True)
    authorize.add_argument("--plan-audit", type=Path, required=True)
    authorize.add_argument("--model-freeze", type=Path, required=True)
    authorize.add_argument("--human-reference-receipt", type=Path, required=True)
    authorize.add_argument("--authorized-at-utc", required=True)
    authorize.add_argument("--operator-run-id", required=True)
    authorize.add_argument("--output-private-gold-manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "freeze-protocol":
        output = freeze_model_protocol(
            _read(args.scale_manifest),
            _read(args.scale_result),
            _read(args.scale_integration_result),
            _read(args.model_manifest),
            source_root=args.source_root,
            source_archive_sha256=sha256_file(args.source_archive),
            scale_manifest_file_sha256=sha256_file(args.scale_manifest),
            scale_result_file_sha256=sha256_file(args.scale_result),
            scale_integration_result_file_sha256=sha256_file(
                args.scale_integration_result
            ),
            model_manifest_file_sha256=sha256_file(args.model_manifest),
            gpu_environment_file_sha256=sha256_file(args.gpu_environment),
            gpu_summary_file_sha256=sha256_file(args.gpu_summary),
            integration_environment_file_sha256=sha256_file(
                args.integration_environment
            ),
            integration_database_file_sha256=sha256_file(
                args.integration_database
            ),
            frozen_at_utc=args.frozen_at_utc,
            operator_run_id=args.operator_run_id,
        )
        _write(args.output, output)
        print(
            json.dumps(
                {
                    "freeze_sha256": output["freeze_sha256"],
                    "scale_article_count": output["scale_article_count"],
                    "gold_prediction_authorized": output["gold_prediction_authorized"],
                },
                indent=2,
            )
        )
    else:
        output = authorize_gold20_prediction(
            _read(args.plan),
            _read(args.screen),
            _read(args.plan_audit),
            _read(args.model_freeze),
            _read(args.human_reference_receipt),
            authorized_at_utc=args.authorized_at_utc,
            operator_run_id=args.operator_run_id,
        )
        _write(args.output_private_gold_manifest, output)
        print(
            json.dumps(
                {
                    "manifest_sha256": output["manifest_sha256"],
                    "article_count": output["article_count"],
                    "contains_human_reference_labels": output[
                        "contains_human_reference_labels"
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

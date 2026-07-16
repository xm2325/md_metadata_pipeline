from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mdmeta.gold_reference import (
    freeze_gold_reference,
    prepare_gold_adjudication,
    seal_annotation_submission,
)


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sources(args: argparse.Namespace) -> tuple[dict, dict, dict]:
    return _read(args.plan), _read(args.screen), _read(args.plan_audit)


def _add_sources(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--plan-audit", type=Path, required=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seal, adjudicate and freeze a leakage-controlled dual-human gold reference."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seal = subparsers.add_parser("seal-submission")
    _add_sources(seal)
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)

    prepare = subparsers.add_parser("prepare-adjudication")
    _add_sources(prepare)
    prepare.add_argument("--annotator-a", type=Path, required=True)
    prepare.add_argument("--annotator-b", type=Path, required=True)
    prepare.add_argument("--output-template", type=Path, required=True)
    prepare.add_argument("--output-private-comparison", type=Path, required=True)

    freeze = subparsers.add_parser("freeze")
    _add_sources(freeze)
    freeze.add_argument("--annotator-a", type=Path, required=True)
    freeze.add_argument("--annotator-b", type=Path, required=True)
    freeze.add_argument("--adjudication", type=Path, required=True)
    freeze.add_argument("--frozen-at-utc", required=True)
    freeze.add_argument("--operator-run-id", required=True)
    freeze.add_argument("--output-private-reference", type=Path, required=True)
    freeze.add_argument("--output-public-receipt", type=Path, required=True)
    args = parser.parse_args()

    plan, screen, plan_audit = _sources(args)
    if args.command == "seal-submission":
        output = seal_annotation_submission(
            _read(args.input), plan, screen, plan_audit
        )
        _write(args.output, output)
        print(
            json.dumps(
                {
                    "article_count": len(output["articles"]),
                    "submission_sha256": output["submission_sha256"],
                },
                indent=2,
            )
        )
    elif args.command == "prepare-adjudication":
        template, comparison = prepare_gold_adjudication(
            plan,
            screen,
            plan_audit,
            _read(args.annotator_a),
            _read(args.annotator_b),
        )
        _write(args.output_template, template)
        _write(args.output_private_comparison, comparison)
        print(
            json.dumps(
                {
                    "article_count": comparison["article_count"],
                    "disagreement_count": comparison["disagreement_count"],
                },
                indent=2,
            )
        )
    else:
        private_reference, public_receipt = freeze_gold_reference(
            plan,
            screen,
            plan_audit,
            _read(args.annotator_a),
            _read(args.annotator_b),
            _read(args.adjudication),
            frozen_at_utc=args.frozen_at_utc,
            operator_run_id=args.operator_run_id,
        )
        _write(args.output_private_reference, private_reference)
        _write(args.output_public_receipt, public_receipt)
        print(json.dumps(public_receipt, indent=2))


if __name__ == "__main__":
    main()

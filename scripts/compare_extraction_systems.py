from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from mdmeta.benchmarking import compare_systems, load_event_run, validated_union


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _system(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("--system must use NAME=PATH")
    return name, Path(path)


def _markdown(payload: dict) -> str:
    lines = [
        "# Extractor comparison",
        "",
        f"Reference documents: {payload['reference_document_count']}",
        "",
        "| System | Events | Attribute P | Attribute R | Attribute F1 | Strict F1 | Median ms | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in payload["systems"].items():
        operational = result["operational"]
        scientific = result["scientific"]
        attributes = scientific["event_attribute"]
        exact = scientific["event_exact"]
        latency = operational["median_latency_ms"]
        tokens = operational["total_tokens"]
        lines.append(
            f"| {name} | {operational['event_count']} | {attributes['precision']:.3f} | "
            f"{attributes['recall']:.3f} | {attributes['f1']:.3f} | {exact['f1']:.3f} | "
            f"{latency if latency is not None else 'n/a'} | "
            f"{tokens if tokens is not None else 'n/a'} |"
        )
    if payload["paired_deltas_vs_baseline"]:
        lines.extend(["", "## Paired differences", ""])
        for name, result in payload["paired_deltas_vs_baseline"].items():
            interval = result["paired_article_bootstrap_95_ci"]
            lines.append(
                f"- **{name} vs {payload['baseline']}**: ΔF1="
                f"{result['observed_delta']:.3f}, 95% paired article-bootstrap CI "
                f"[{interval[0]:.3f}, {interval[1]:.3f}], "
                f"P(Δ>0)={result['bootstrap_probability_delta_gt_zero']:.3f}."
            )
    lines.extend(["", "## Scientific boundary", "", payload["scientific_boundary"]])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare deterministic, LLM and validated-hybrid protocol-event systems."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--system", action="append", type=_system, required=True)
    parser.add_argument("--baseline")
    parser.add_argument(
        "--hybrid",
        nargs=3,
        metavar=("NAME", "LEFT", "RIGHT"),
        action="append",
        default=[],
        help="Add a validated union of two named systems.",
    )
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=3997)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    references, _ = load_event_run(args.reference)
    systems = {name: load_event_run(path) for name, path in args.system}
    if len(systems) != len(args.system):
        raise ValueError("system names must be unique")
    for name, left, right in args.hybrid:
        if name in systems:
            raise ValueError(f"duplicate system name: {name}")
        if left not in systems or right not in systems:
            raise ValueError(f"hybrid inputs must name existing systems: {left}, {right}")
        events = validated_union(systems[left][0], systems[right][0])
        systems[name] = (
            events,
            {
                "source": f"validated_union:{left}+{right}",
                "model_id": None,
                "completions": [],
            },
        )

    result = compare_systems(
        references,
        systems,
        baseline_name=args.baseline,
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    _atomic_write(args.output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.markdown is not None:
        _atomic_write(args.markdown, _markdown(result))
    print(
        json.dumps(
            {
                "reference_documents": result["reference_document_count"],
                "systems": list(result["systems"]),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

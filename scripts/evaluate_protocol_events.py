from __future__ import annotations

import argparse
import json
from pathlib import Path

from mdmeta.event_evaluation import evaluate_events
from mdmeta.models import ProtocolEvent


def load_events(path: Path) -> dict[str, list[ProtocolEvent]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["documents"] if isinstance(payload, dict) and "documents" in payload else payload
    return {
        document_id: [ProtocolEvent.model_validate(item) for item in events]
        for document_id, events in rows.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate phase-aware protocol events.")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=3997)
    args = parser.parse_args()

    result = evaluate_events(
        load_events(args.predictions),
        load_events(args.references),
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path

import typer

from .annotation import compare_annotators, load_annotations, write_adjudication_template
from .audit import validation_audit
from .benchmark import create_benchmark_plan, load_candidates
from .clients import EuropePMCClient
from .evaluation import evaluate
from .models import MDRecord
from .pipeline import run_pipeline

app = typer.Typer(no_args_is_help=True)


@app.command()
def extract(
    xml: Path = typer.Option(..., exists=True, readable=True),
    document_id: str = typer.Option(...),
    source_uri: str = typer.Option(...),
    output_dir: Path = typer.Option(...),
    extractor_version: str = typer.Option("v2", help="v1 or v2"),
    live_validation: bool = typer.Option(False, help="Call PDBe and UniProt APIs."),
) -> None:
    if extractor_version not in {"v1", "v2"}:
        raise typer.BadParameter("extractor-version must be v1 or v2")
    record = run_pipeline(
        xml,
        document_id,
        source_uri,
        output_dir,
        live_validation=live_validation,
        extractor_version=extractor_version,
    )
    typer.echo(
        f"Wrote {len(record.facts)} facts and {len(record.protocol_events)} protocol events to {output_dir}"
    )


@app.command("fetch-europe-pmc")
def fetch_europe_pmc(
    pmcid: str = typer.Option(...),
    output: Path = typer.Option(...),
) -> None:
    text, digest, url = EuropePMCClient().full_text_xml(pmcid)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    typer.echo(f"Downloaded {url}; sha256={digest}; output={output}")


@app.command()
def schema(output: Path = typer.Option(...)) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(MDRecord.model_json_schema(), indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("evaluate")
def evaluate_record(
    record: Path = typer.Option(..., exists=True),
    gold: Path = typer.Option(..., exists=True),
    output: Path = typer.Option(...),
) -> None:
    parsed_record = MDRecord.model_validate_json(record.read_text(encoding="utf-8"))
    parsed_gold = json.loads(gold.read_text(encoding="utf-8"))
    result = evaluate(parsed_record, parsed_gold)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    typer.echo(json.dumps(result, indent=2))


@app.command("benchmark-plan")
def benchmark_plan(
    candidates: Path = typer.Option(..., exists=True),
    output: Path = typer.Option(...),
    excluded_ids: Path | None = typer.Option(None, exists=True),
    seed: int = typer.Option(3997),
) -> None:
    excluded = set()
    if excluded_ids is not None:
        excluded = {
            line.strip()
            for line in excluded_ids.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    plan = create_benchmark_plan(
        load_candidates(candidates), seed=seed, excluded_document_ids=excluded
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote locked plan {plan.plan_sha256} to {output}")


@app.command("compare-annotations")
def compare_annotations_command(
    annotator_a: Path = typer.Option(..., exists=True),
    annotator_b: Path = typer.Option(..., exists=True),
    output: Path = typer.Option(...),
    adjudication_template: Path | None = typer.Option(None),
) -> None:
    result = compare_annotators(load_annotations(annotator_a), load_annotations(annotator_b))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if adjudication_template is not None:
        adjudication_template.parent.mkdir(parents=True, exist_ok=True)
        write_adjudication_template(result, adjudication_template)
    typer.echo(json.dumps({k: result[k] for k in result if k != "disagreements"}, indent=2))


@app.command("validation-audit")
def validation_audit_command(
    record: Path = typer.Option(..., exists=True), output: Path = typer.Option(...)
) -> None:
    parsed = MDRecord.model_validate_json(record.read_text(encoding="utf-8"))
    result = validation_audit(parsed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    typer.echo(json.dumps(result, indent=2))


@app.command()
def serve(
    database: Path = typer.Option(..., exists=True),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter("Install the api extra: pip install -e '.[api]'") from exc
    from .api import create_app

    uvicorn.run(create_app(database), host=host, port=port)


if __name__ == "__main__":
    app()

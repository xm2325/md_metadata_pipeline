from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path, PurePath, PureWindowsPath

from fastapi import FastAPI, HTTPException, Query

from . import __version__
from .storage import SCHEMA_VERSION, SQLiteRecordStore


def _public_record(record: dict) -> dict:
    payload = deepcopy(record)
    article = payload.get("article", {})
    if isinstance(article, dict) and str(article.get("source_uri", "")).startswith("file:"):
        article["source_uri"] = None
    for asset in payload.get("provenance", {}).get("assets", []):
        if isinstance(asset, dict):
            asset["local_path"] = None
            if str(asset.get("source_uri", "")).startswith("file:"):
                asset["source_uri"] = None
    for step in payload.get("provenance", {}).get("workflow_steps", []):
        if not isinstance(step, dict):
            continue
        for field in ("inputs", "outputs"):
            values = step.get(field, [])
            if not isinstance(values, list):
                continue
            step[field] = [
                "<redacted-local-path>"
                if isinstance(value, str)
                and (
                    value.startswith("file:")
                    or PurePath(value).is_absolute()
                    or PureWindowsPath(value).is_absolute()
                )
                else value
                for value in values
            ]
    return payload


def create_app(
    database_path: str | Path,
    *,
    read_only: bool = False,
    dataset_sha256: str = "unversioned",
    build_sha: str = "unknown",
) -> FastAPI:
    store = SQLiteRecordStore(database_path, read_only=read_only)
    app = FastAPI(
        title="MD Metadata Integration API",
        version=__version__,
        description="Evidence-linked literature, PDBe, UniProt, SIFTS and provenance records.",
    )
    app.state.record_store = store

    @app.get("/health")
    def health() -> dict[str, int | str]:
        return {"status": "ok", "article_count": store.count_articles()}

    @app.get("/livez")
    def liveness() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readiness() -> dict[str, int | str]:
        try:
            article_count = store.count_articles()
            schema_version = store.schema_version()
        except (sqlite3.Error, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        if schema_version != SCHEMA_VERSION:
            raise HTTPException(status_code=503, detail="database schema incompatible")
        return {
            "status": "ready",
            "version": __version__,
            "database_schema_version": schema_version,
            "article_count": article_count,
        }

    @app.get("/metadata")
    def metadata() -> dict[str, int | str]:
        return {
            "service": "md-metadata-pipeline",
            "version": __version__,
            "record_schema": "integrated-md-record-v1",
            "database_schema_version": store.schema_version(),
            "article_count": store.count_articles(),
            "database_mode": "read_only" if store.read_only else "read_write",
            "dataset_sha256": dataset_sha256,
            "build_sha": build_sha,
        }

    @app.get("/records/{document_id}")
    def get_record(document_id: str) -> dict:
        record = store.get(document_id.upper())
        if record is None:
            raise HTTPException(status_code=404, detail="record not found")
        return _public_record(record)

    @app.get("/search")
    def search(
        pdb_id: str | None = Query(default=None, min_length=4, max_length=4),
        uniprot_accession: str | None = Query(default=None, min_length=6, max_length=10),
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict:
        if pdb_id is None and uniprot_accession is None:
            raise HTTPException(
                status_code=400,
                detail="supply pdb_id or uniprot_accession",
            )
        records = store.search(
            pdb_id=pdb_id,
            uniprot_accession=uniprot_accession,
            limit=limit,
        )
        return {"count": len(records), "records": [_public_record(row) for row in records]}

    return app

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from .storage import SQLiteRecordStore


def create_app(database_path: str | Path) -> FastAPI:
    store = SQLiteRecordStore(database_path)
    app = FastAPI(
        title="MD Metadata Integration API",
        version="0.8.0",
        description="Evidence-linked literature, PDBe, UniProt, SIFTS and provenance records.",
    )

    @app.get("/health")
    def health() -> dict[str, int | str]:
        return {"status": "ok", "article_count": store.count_articles()}

    @app.get("/records/{document_id}")
    def get_record(document_id: str) -> dict:
        record = store.get(document_id.upper())
        if record is None:
            raise HTTPException(status_code=404, detail="record not found")
        return record

    @app.get("/search")
    def search(
        pdb_id: str | None = Query(default=None, min_length=4, max_length=4),
        uniprot_accession: str | None = Query(default=None, min_length=6, max_length=10),
    ) -> dict:
        if pdb_id is None and uniprot_accession is None:
            raise HTTPException(
                status_code=400,
                detail="supply pdb_id or uniprot_accession",
            )
        records = store.search(
            pdb_id=pdb_id,
            uniprot_accession=uniprot_accession,
        )
        return {"count": len(records), "records": records}

    return app

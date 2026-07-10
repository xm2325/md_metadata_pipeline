from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query


def create_app(database: str | Path) -> FastAPI:
    database = str(database)
    app = FastAPI(title="MD literature audit API", version="0.2.0")

    def rows(query: str, params: tuple = ()) -> list[dict]:
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/records/{document_id}")
    def record(document_id: str) -> dict:
        items = rows("SELECT * FROM article WHERE document_id = ?", (document_id,))
        if not items:
            raise HTTPException(status_code=404, detail="record not found")
        return items[0]

    @app.get("/records/{document_id}/facts")
    def facts(document_id: str) -> list[dict]:
        items = rows(
            "SELECT * FROM fact WHERE document_id = ? ORDER BY field_name, fact_id", (document_id,)
        )
        for item in items:
            item["normalized_value"] = json.loads(item["normalized_value"])
        return items

    @app.get("/records/{document_id}/protocol-events")
    def protocol_events(document_id: str) -> list[dict]:
        return rows(
            "SELECT * FROM protocol_event WHERE document_id = ? ORDER BY event_order",
            (document_id,),
        )

    @app.get("/search")
    def search(
        field_name: str = Query(min_length=1),
        normalized_value: str = Query(min_length=1),
    ) -> list[dict]:
        encoded_candidates = (
            normalized_value,
            json.dumps(normalized_value),
            json.dumps(int(normalized_value)) if normalized_value.isdigit() else "",
        )
        placeholders = ",".join("?" for _ in encoded_candidates)
        return rows(
            f"SELECT * FROM fact WHERE field_name = ? AND normalized_value IN ({placeholders}) ORDER BY fact_id",
            (field_name, *encoded_candidates),
        )

    return app

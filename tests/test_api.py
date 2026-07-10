from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI

from mdlit.api import create_app
from mdlit.pipeline import run_pipeline


async def _asgi_get(
    app: FastAPI, path: str, params: dict[str, str] | None = None
) -> tuple[int, object]:
    messages: list[dict] = []
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    query = urlencode(params or {}).encode("ascii")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query,
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(body)


def _get(app: FastAPI, path: str, params: dict[str, str] | None = None) -> tuple[int, object]:
    return asyncio.run(_asgi_get(app, path, params))


def test_api_reads_sqlite(tmp_path: Path) -> None:
    run_pipeline("data/demo/article.xml", "DOC", "synthetic://doc", tmp_path)
    app = create_app(tmp_path / "audit.sqlite")

    status, body = _get(app, "/health")
    assert status == 200
    assert body == {"status": "ok"}

    status, _ = _get(app, "/records/DOC")
    assert status == 200

    status, facts = _get(app, "/records/DOC/facts")
    assert status == 200
    assert isinstance(facts, list)
    assert len(facts) == 12

    status, result = _get(
        app,
        "/search",
        {"field_name": "program", "normalized_value": "GROMACS"},
    )
    assert status == 200
    assert isinstance(result, list)
    assert len(result) == 1


def test_api_returns_404(tmp_path: Path) -> None:
    run_pipeline("data/demo/article.xml", "DOC", "synthetic://doc", tmp_path)
    status, body = _get(create_app(tmp_path / "audit.sqlite"), "/records/MISSING")
    assert status == 404
    assert body == {"detail": "record not found"}

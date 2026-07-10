from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

DEFAULT_QUERY = (
    'OPEN_ACCESS:Y AND HAS_FT:Y AND '
    '(TITLE_ABS:"molecular dynamics" OR TITLE_ABS:"MD simulation")'
)
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SOFTWARE_PATTERNS = {
    "gromacs": re.compile(r"\bgromacs\b", re.I),
    "amber": re.compile(r"\bamber(?:tools)?\b", re.I),
    "namd": re.compile(r"\bnamd\b", re.I),
    "openmm": re.compile(r"\bopenmm\b", re.I),
    "charmm": re.compile(r"\bcharmm\b", re.I),
    "desmond": re.compile(r"\bdesmond\b", re.I),
}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def software_family(text: str) -> str:
    matches = [name for name, pattern in SOFTWARE_PATTERNS.items() if pattern.search(text)]
    return "+".join(matches) if matches else "unknown"


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _article(row: dict[str, Any]) -> dict[str, Any] | None:
    pmcid = str(row.get("pmcid") or "").upper()
    if not pmcid.startswith("PMC"):
        return None
    title = " ".join(str(row.get("title") or pmcid).split())
    abstract = " ".join(str(row.get("abstractText") or "").split())
    year_text = str(row.get("pubYear") or "")
    return {
        "document_id": pmcid,
        "title": title,
        "source_uri": f"https://europepmc.org/articles/{pmcid}",
        "doi": row.get("doi"),
        "year": int(year_text) if year_text.isdigit() else None,
        "software_family": software_family(f"{title} {abstract}"),
        "licence": row.get("license"),
        "full_text_available": True,
        "source_sha256": None,
    }


def _bounded_retry_after(response: httpx.Response | None, fallback: float) -> float:
    if response is None:
        return fallback
    raw = response.headers.get("Retry-After")
    if raw is None:
        return fallback
    try:
        return min(max(float(raw), 0.0), 30.0)
    except ValueError:
        return fallback


def _get_page_with_retry(
    client: httpx.Client,
    *,
    params: dict[str, Any],
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.get(BASE_URL, params=params)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"retryable Europe PMC status {response.status_code}",
                request=response.request,
                response=response,
            )
        except httpx.TransportError as exc:
            last_error = exc
        except httpx.HTTPStatusError:
            raise
        if attempt == retries:
            break
        fallback = min(2.0**attempt, 20.0)
        sleep(_bounded_retry_after(response, fallback))
    raise RuntimeError(
        f"Europe PMC page request failed after {retries + 1} attempts; "
        f"cursor={params.get('cursorMark')!r}"
    ) from last_error


def query_articles(
    query: str,
    *,
    max_candidates: int = 500,
    page_size: int = 100,
    timeout: float = 30.0,
    retries: int = 5,
) -> dict[str, Any]:
    articles: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    cursor = "*"
    headers = {"User-Agent": "md-metadata-pipeline/0.7 confirmatory-corpus"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        while len(articles) < max_candidates:
            response = _get_page_with_retry(
                client,
                params={
                    "query": query,
                    "format": "json",
                    "resultType": "core",
                    "pageSize": page_size,
                    "cursorMark": cursor,
                },
                retries=retries,
            )
            payload = response.json()
            pages.append(
                {
                    "cursor_mark": cursor,
                    "response_sha256": hashlib.sha256(response.content).hexdigest(),
                    "hit_count": payload.get("hitCount"),
                }
            )
            rows = payload.get("resultList", {}).get("result", [])
            for row in rows:
                article = _article(row)
                if article is not None:
                    articles.append(article)
                    if len(articles) >= max_candidates:
                        break
            next_cursor = payload.get("nextCursorMark")
            if not rows or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    result = {
        "query": query,
        "endpoint": BASE_URL,
        "articles": articles,
        "pages": pages,
    }
    result["manifest_sha256"] = _canonical_hash(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Europe PMC metadata only.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-candidates", type=int, default=500)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args()

    result = query_articles(
        args.query,
        max_candidates=args.max_candidates,
        page_size=args.page_size,
        retries=args.retries,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "articles": len(result["articles"]),
                "pages": len(result["pages"]),
                "manifest_sha256": result["manifest_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

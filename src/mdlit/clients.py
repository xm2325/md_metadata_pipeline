from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx


class CachedHTTPClient:
    def __init__(
        self,
        cache_dir: str | Path = ".cache/mdlit",
        timeout_seconds: float = 20.0,
        retries: int = 2,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.headers = {
            "User-Agent": "md-metadata-pipeline/0.2.0 (research software; contact via repository)",
            "Accept": "application/json, application/xml, text/xml;q=0.9, */*;q=0.1",
        }

    def _cache_path(self, url: str, suffix: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.{suffix}"

    def get_bytes(self, url: str, use_cache: bool = True) -> bytes:
        cache_path = self._cache_path(url, "bin")
        if use_cache and cache_path.exists():
            return cache_path.read_bytes()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds, headers=self.headers, follow_redirects=True
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    cache_path.write_bytes(response.content)
                    return response.content
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"GET failed after retries: {url}") from last_error

    def get_json(self, url: str, use_cache: bool = True) -> tuple[Any, str]:
        payload = self.get_bytes(url, use_cache=use_cache)
        return json.loads(payload), hashlib.sha256(payload).hexdigest()

    def get_text(self, url: str, use_cache: bool = True) -> tuple[str, str]:
        payload = self.get_bytes(url, use_cache=use_cache)
        return payload.decode("utf-8"), hashlib.sha256(payload).hexdigest()


class EuropePMCClient:
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, http: CachedHTTPClient | None = None) -> None:
        self.http = http or CachedHTTPClient()

    def full_text_xml(self, pmcid: str) -> tuple[str, str, str]:
        pmcid = pmcid.upper()
        url = f"{self.base_url}/{pmcid}/fullTextXML"
        text, digest = self.http.get_text(url)
        return text, digest, url

    def search(
        self,
        query: str,
        *,
        page_size: int = 100,
        cursor_mark: str = "*",
        result_type: str = "core",
    ) -> tuple[Any, str, str]:
        """Search Europe PMC and return the raw response with a content hash."""
        from urllib.parse import urlencode

        params = urlencode(
            {
                "query": query,
                "format": "json",
                "pageSize": page_size,
                "cursorMark": cursor_mark,
                "resultType": result_type,
            }
        )
        url = f"{self.base_url}/search?{params}"
        data, digest = self.http.get_json(url)
        return data, digest, url


class PDBeClient:
    base_url = "https://www.ebi.ac.uk/pdbe/api"

    def __init__(self, http: CachedHTTPClient | None = None) -> None:
        self.http = http or CachedHTTPClient()

    def entry_summary(self, pdb_id: str) -> tuple[Any, str, str]:
        pdb_id = pdb_id.lower()
        url = f"{self.base_url}/pdb/entry/summary/{pdb_id}"
        data, digest = self.http.get_json(url)
        return data, digest, url

    def uniprot_mapping(self, pdb_id: str) -> tuple[Any, str, str]:
        pdb_id = pdb_id.lower()
        url = f"{self.base_url}/mappings/uniprot/{pdb_id}"
        data, digest = self.http.get_json(url)
        return data, digest, url


class UniProtClient:
    base_url = "https://rest.uniprot.org/uniprotkb"

    def __init__(self, http: CachedHTTPClient | None = None) -> None:
        self.http = http or CachedHTTPClient()

    def entry(self, accession: str) -> tuple[Any, str, str]:
        accession = accession.upper()
        url = f"{self.base_url}/{accession}.json"
        data, digest = self.http.get_json(url)
        return data, digest, url

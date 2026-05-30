"""Semantic Scholar search backend.

Free, no-auth public API at https://api.semanticscholar.org/graph/v1.
Rate-limited (100 req/5 min for unauthenticated). Returns up to 100
papers per query. Higher limits with an API key, but we do not rely
on one.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Paper, SearchQuery

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = (
    "paperId,externalIds,title,authors,year,venue,abstract,citationCount,url"
)
USER_AGENT = "E2SA-LitSearchAgent/0.1.0"


class SemanticScholarClient:
    """Client for the Semantic Scholar Graph API."""

    def __init__(
        self,
        base_url: str = SEMANTIC_SCHOLAR_BASE,
        timeout: float = 30.0,
        retry_attempts: int = 5,
        retry_backoff: float = 5.0,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff

    def search_papers(self, query: SearchQuery) -> list[Paper]:
        """Run a paper relevance search and return normalized Paper records."""
        params: dict[str, Any] = {
            "query": query.query,
            "limit": min(query.limit, 100),
            "fields": DEFAULT_FIELDS,
        }
        if query.year_min and query.year_max:
            params["year"] = f"{query.year_min}-{query.year_max}"
        elif query.year_min:
            params["year"] = f"{query.year_min}-"
        elif query.year_max:
            params["year"] = f"-{query.year_max}"
        if query.fields_of_study:
            params["fieldsOfStudy"] = ",".join(query.fields_of_study)

        url = f"{self.base_url}/paper/search?{urlencode(params)}"
        payload = self._fetch_json(url)
        raw_papers = payload.get("data", [])
        return [self._to_paper(p) for p in raw_papers if p.get("title")]

    def _fetch_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                req = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as e:
                last_error = e
                if e.code == 429:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except ValueError:
                            wait = self.retry_backoff * (attempt + 1)
                    else:
                        wait = self.retry_backoff * (attempt + 1) * 2
                    time.sleep(wait)
                    continue
                if 500 <= e.code < 600:
                    time.sleep(self.retry_backoff * (attempt + 1))
                    continue
                raise
            except URLError as e:
                last_error = e
                time.sleep(self.retry_backoff * (attempt + 1))
                continue
        raise RuntimeError(
            f"Semantic Scholar request failed after {self.retry_attempts} attempts: {last_error}"
        )

    def _to_paper(self, raw: dict[str, Any]) -> Paper:
        external_ids = raw.get("externalIds") or {}
        doi = external_ids.get("DOI")
        paper_id = doi or raw.get("paperId") or ""
        authors = [a.get("name", "") for a in (raw.get("authors") or []) if a.get("name")]

        return Paper(
            paper_id=paper_id,
            doi=doi,
            title=raw.get("title") or "",
            authors=authors,
            year=raw.get("year"),
            venue=raw.get("venue"),
            abstract=raw.get("abstract"),
            source_url=raw.get("url"),
            citation_count=raw.get("citationCount"),
            source_backend="semantic_scholar",
            verified=False,
            extra={"externalIds": external_ids},
        )

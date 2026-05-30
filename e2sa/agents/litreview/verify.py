"""CrossRef DOI verifier.

Uses https://api.crossref.org/works/{doi} to verify DOIs and enrich
metadata. Free, no auth required. Adheres to CrossRef etiquette by
including a User-Agent and rate-limiting requests.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .models import Paper

CROSSREF_BASE = "https://api.crossref.org/works"
USER_AGENT = "E2SA-LitSearchAgent/0.1.0 (mailto:jingtao@lbl.gov)"
RATE_LIMIT_SECONDS = 0.1  # Be polite, even though CrossRef permits more


class CrossRefVerifier:
    """Verify DOIs and enrich Paper records with CrossRef metadata."""

    def __init__(
        self,
        base_url: str = CROSSREF_BASE,
        timeout: float = 20.0,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time = 0.0

    def verify(self, doi: str) -> dict[str, Any] | None:
        """Look up a DOI on CrossRef. Return metadata dict or None if not found."""
        if not doi:
            return None

        self._respect_rate_limit()
        url = f"{self.base_url}/{quote(doi, safe='/.')}"
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 404:
                return None
            raise
        except URLError:
            return None

        return payload.get("message")

    def enrich_paper(self, paper: Paper) -> Paper:
        """Verify a Paper's DOI and merge CrossRef metadata into it."""
        if not paper.doi:
            return paper

        message = self.verify(paper.doi)
        if not message:
            return paper

        title = paper.title
        if not title and message.get("title"):
            title = message["title"][0]

        year = paper.year
        if not year:
            issued = message.get("issued", {}).get("date-parts", [[]])[0]
            if issued:
                year = issued[0]

        authors = paper.authors
        if not authors and message.get("author"):
            authors = [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in message["author"]
                if a.get("family")
            ]

        venue = paper.venue
        if not venue:
            container = message.get("container-title")
            if container:
                venue = container[0]

        return paper.model_copy(
            update={
                "title": title,
                "year": year,
                "authors": authors,
                "venue": venue,
                "verified": True,
            }
        )

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_time = time.monotonic()

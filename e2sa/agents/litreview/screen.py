"""LLM-driven relevance screening for literature review papers.

After themed search returns a candidate set of papers, this module asks
Claude to rate each paper as HIGH / MEDIUM / LOW / IRRELEVANT against
the original research topic and project context. Returns the input
list with relevance labels attached, with IRRELEVANT papers dropped
by default.

Mirrors stage 4 (triage and curate) of Jing's manual phosphorus
literature review workflow.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from .llm import LLM
from .models import Paper

Relevance = Literal["HIGH", "MEDIUM", "LOW", "IRRELEVANT"]

SCREEN_SYSTEM = """You are a literature review triager.

Given a research topic, optional project context, and a numbered list of paper abstracts, classify each paper's relevance to the topic. Use four levels:

- HIGH: directly addresses the topic. Methods, datasets, or findings the researcher would cite or build on.
- MEDIUM: adjacent or methodological. Useful background or transferable techniques.
- LOW: tangentially related. Same domain but different question or system.
- IRRELEVANT: off-topic. Should be dropped.

Be strict. The goal is a clean corpus of relevant papers, not maximum recall. When in doubt between LOW and IRRELEVANT, choose IRRELEVANT.

Return ONLY a JSON array with one object per input paper, in the same order. Each object has:
- "index": the paper's 1-based index from the input
- "relevance": one of "HIGH", "MEDIUM", "LOW", "IRRELEVANT"
- "reason": one short sentence (max 20 words) explaining the rating

Example:

[
  {"index": 1, "relevance": "HIGH", "reason": "Direct methodology for ground ice mapping with InSAR in Alaska."},
  {"index": 2, "relevance": "IRRELEVANT", "reason": "Biomedical paper on protein folding, unrelated to permafrost."}
]
"""

DEFAULT_BATCH_SIZE = 10


def screen_papers(
    papers: list[Paper],
    topic: str,
    context: str = "",
    llm: LLM | None = None,
    drop_irrelevant: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seeds: list[Paper] | None = None,
) -> list[Paper]:
    """Score papers for relevance and return enriched (or filtered) list.

    Args:
        papers: Candidate Paper records from a search.
        topic: The original research topic.
        context: Optional longer project description.
        llm: An LLM implementation. If None, constructs an AnthropicLLM.
        drop_irrelevant: If True, remove papers rated IRRELEVANT. If False,
            keep all papers and only attach the rating to `extra`.
        batch_size: How many papers to send to the LLM per call. Smaller
            batches use more API calls but keep individual prompts short.

    Returns:
        List of Paper objects with `extra["relevance"]` and `extra["relevance_reason"]`
        populated. If drop_irrelevant=True, IRRELEVANT papers are removed.
    """
    if not papers:
        return []
    if llm is None:
        from .llm import AnthropicLLM

        llm = AnthropicLLM()

    enriched: list[Paper] = []
    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        ratings = _screen_batch(batch, topic, context, llm, seeds=seeds)
        for paper, rating in zip(batch, ratings):
            relevance = rating.get("relevance", "LOW")
            reason = rating.get("reason", "")
            if drop_irrelevant and relevance == "IRRELEVANT":
                continue
            new_extra = dict(paper.extra)
            new_extra["relevance"] = relevance
            new_extra["relevance_reason"] = reason
            enriched.append(paper.model_copy(update={"extra": new_extra}))

    return enriched


def _screen_batch(
    batch: list[Paper],
    topic: str,
    context: str,
    llm: LLM,
    seeds: list[Paper] | None = None,
) -> list[dict]:
    """Run one LLM call to rate a batch of papers."""
    user_prompt = _build_user_prompt(batch, topic, context, seeds)
    response = llm.complete(
        system=SCREEN_SYSTEM,
        user=user_prompt,
        max_tokens=2048,
    )
    parsed = _parse_ratings(response, expected_count=len(batch))
    return parsed


def _build_user_prompt(
    batch: list[Paper],
    topic: str,
    context: str,
    seeds: list[Paper] | None = None,
) -> str:
    parts = [f"Topic: {topic}"]
    if context:
        truncated = context if len(context) <= 6_000 else context[:6_000] + "\n...[truncated]"
        parts.extend(["", "Project context:", truncated])
    if seeds:
        parts.extend(
            [
                "",
                "HIGH-relevance positive examples (curated seed papers, all known to be on-topic):",
            ]
        )
        for seed in seeds[:8]:  # cap at 8 to keep prompt size sane
            seed_line = f"- {seed.title}"
            if seed.year:
                seed_line += f" ({seed.year})"
            parts.append(seed_line)
        parts.append(
            "Use these as a calibration for what HIGH relevance looks like for this topic."
        )
    parts.extend(["", "Papers to rate:"])
    for i, paper in enumerate(batch, start=1):
        title = paper.title or "(no title)"
        abstract = paper.abstract or "(no abstract)"
        if len(abstract) > 800:
            abstract = abstract[:800] + "..."
        parts.append(f"\n{i}. {title}")
        parts.append(f"   {abstract}")
    parts.append("")
    parts.append(
        f"Return a JSON array with exactly {len(batch)} objects, in order."
    )
    return "\n".join(parts)


def _parse_ratings(response: str, expected_count: int) -> list[dict]:
    """Extract a JSON array of rating objects from the LLM response.

    Robustly handles code fences and trailing text. Pads or truncates
    to the expected count so a malformed response degrades gracefully.
    """
    cleaned = response.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            return [{"relevance": "LOW", "reason": "parse error"}] * expected_count
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [{"relevance": "LOW", "reason": "parse error"}] * expected_count

    if not isinstance(data, list):
        return [{"relevance": "LOW", "reason": "parse error"}] * expected_count

    ratings: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        relevance = item.get("relevance", "LOW")
        if relevance not in {"HIGH", "MEDIUM", "LOW", "IRRELEVANT"}:
            relevance = "LOW"
        ratings.append(
            {
                "relevance": relevance,
                "reason": str(item.get("reason", ""))[:200],
            }
        )

    # Pad or truncate to expected count
    while len(ratings) < expected_count:
        ratings.append({"relevance": "LOW", "reason": "no rating returned"})
    return ratings[:expected_count]

"""LLM-driven theme decomposition for literature reviews.

Takes a research topic plus optional project context and asks Claude to
extract 8-12 focused single-concept search queries that together cover
the topic. Mirrors the manual phosphorus literature review workflow
where Claude broke "P and critical minerals in plant-soil-microbe
systems" into 12 themes (P cycling, root exudates, AM fungi, etc.).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .llm import LLM

DECOMPOSE_SYSTEM = """You are a literature review planner.

Given a research topic and optional project context, decompose the topic into 8 to 12 focused single-concept search queries that, taken together, cover the topic. Each query must:

- Be 2 to 5 words long
- Use natural keywords (no boolean operators, no quotes)
- Cover one specific concept, method, or sub-topic
- Be suitable for direct submission to an academic search API like arXiv, PubMed, or Semantic Scholar
- Together span the breadth of the topic (methods, observations, theory, applications)

Return ONLY a JSON array of theme strings. No prose, no explanation, just the JSON array. Example:

["permafrost ground ice", "thermokarst lake formation", "InSAR surface subsidence", "active layer thickness", "Arctic soil moisture remote sensing", "ground penetrating radar permafrost", "Alaska permafrost map", "permafrost carbon feedback", "ice wedge degradation", "freeze thaw cycles"]
"""


def decompose_topic(
    topic: str,
    context: str = "",
    llm: LLM | None = None,
    max_themes: int = 12,
) -> list[str]:
    """Use an LLM to decompose a topic into focused search themes.

    Args:
        topic: One-sentence research question or topic statement.
        context: Optional longer project description (e.g., a CLAUDE.md
            file's contents) that gives the model background on what the
            researcher actually cares about.
        llm: An LLM implementation. If None, constructs an AnthropicLLM
            from environment variables.
        max_themes: Soft cap on how many themes to ask for (the LLM may
            return slightly more or fewer).

    Returns:
        A list of theme strings ready to feed into themed search.
    """
    if llm is None:
        from .llm import AnthropicLLM

        llm = AnthropicLLM()

    user_prompt = _build_user_prompt(topic, context, max_themes)
    response = llm.complete(
        system=DECOMPOSE_SYSTEM,
        user=user_prompt,
        max_tokens=2048,
    )
    return _parse_themes(response)


def decompose_topic_from_file(
    topic: str,
    context_file: Path | str,
    llm: LLM | None = None,
    max_themes: int = 12,
) -> list[str]:
    """Decompose a topic with a project context file (CLAUDE.md, README.md, etc.)."""
    context = Path(context_file).read_text(encoding="utf-8")
    return decompose_topic(topic, context=context, llm=llm, max_themes=max_themes)


def _build_user_prompt(topic: str, context: str, max_themes: int) -> str:
    parts = [f"Topic: {topic}", "", f"Return up to {max_themes} themes."]
    if context:
        # Truncate context to avoid blowing the prompt budget. 12K chars
        # is plenty for a CLAUDE.md or research description.
        truncated = context if len(context) <= 12_000 else context[:12_000] + "\n...[truncated]"
        parts = [
            f"Topic: {topic}",
            "",
            "Project context (background on what the researcher cares about):",
            truncated,
            "",
            f"Return up to {max_themes} themes.",
        ]
    return "\n".join(parts)


def _parse_themes(response: str) -> list[str]:
    """Extract a JSON list of strings from the LLM response.

    The model is asked to return only JSON, but in practice it sometimes
    wraps in code fences or adds a trailing comment. Extract the first
    JSON array we can find, then validate the contents.
    """
    cleaned = response.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back: find the first [...] in the response
        match = re.search(r"\[[^\[\]]*\]", cleaned, re.DOTALL)
        if not match:
            raise ValueError(
                f"LLM response did not contain a parseable JSON array. Response: {response[:500]}"
            ) from None
        data = json.loads(match.group(0))

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")

    themes: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        cleaned_item = item.strip()
        if cleaned_item:
            themes.append(cleaned_item)
    return themes

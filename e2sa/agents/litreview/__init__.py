"""LitReviewAgent: literature search, verification, RAG ingestion, and synthesis."""
from .agent import LitReviewAgent, SearchBackend, default_search_backend
from .decompose import decompose_topic, decompose_topic_from_file
from .ingest import ingest_papers
from .llm import LLM, AnthropicLLM, FakeLLM
from .models import Paper, SearchQuery, SearchResult
from .screen import screen_papers
from .search import SemanticScholarClient
from .seeds import load_seeds
from .verify import CrossRefVerifier

try:
    from .paper_search_mcp_backend import PaperSearchMCPBackend
except ImportError:  # paper-search-mcp not installed
    PaperSearchMCPBackend = None  # type: ignore[assignment,misc]

# Backwards-compatible alias for code that referenced the old name
LitSearchAgent = LitReviewAgent

__all__ = [
    "LitReviewAgent",
    "LitSearchAgent",  # alias
    "SearchBackend",
    "default_search_backend",
    "Paper",
    "SearchQuery",
    "SearchResult",
    "SemanticScholarClient",
    "PaperSearchMCPBackend",
    "CrossRefVerifier",
    "ingest_papers",
    "LLM",
    "AnthropicLLM",
    "FakeLLM",
    "decompose_topic",
    "decompose_topic_from_file",
    "screen_papers",
    "load_seeds",
]

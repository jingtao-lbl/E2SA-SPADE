"""CLI for the LitReviewAgent.

Usage:
    python -m e2sa.agents.litreview search "permafrost ground ice content Alaska" \\
        --max 20 --year-min 2015 --no-verify

    python -m e2sa.agents.litreview list --catalog data/lance --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from e2sa.rag.store import open_store

from .agent import LitReviewAgent
from .ingest import existing_chunk_ids
from .models import SearchQuery


def cmd_search(args: argparse.Namespace) -> int:
    search_client = None
    if args.backend == "mcp":
        try:
            from .paper_search_mcp_backend import PaperSearchMCPBackend

            search_client = PaperSearchMCPBackend()
        except ImportError:
            print(
                "ERROR: paper-search-mcp not installed. Run: pip install paper-search-mcp"
            )
            return 1
    elif args.backend == "semantic_scholar":
        from .search import SemanticScholarClient

        search_client = SemanticScholarClient()

    agent = LitReviewAgent(
        store_path=args.catalog,
        search_client=search_client,
        verify_dois=not args.no_verify,
    )

    themes: list[str] = []
    if args.themes:
        themes = [t.strip() for t in args.themes.split(",") if t.strip()]

    query = SearchQuery(
        query=args.query if not themes else "",
        themes=themes,
        limit=args.max,
        year_min=args.year_min,
        year_max=args.year_max,
    )
    backend_name = type(agent.search_client).__name__
    if themes:
        print(f"Searching ({backend_name}) themed mode, {len(themes)} themes:")
        for t in themes:
            print(f"  - {t!r}")
        print(f"  per-theme limit: {args.max}")
    else:
        print(f"Searching ({backend_name}): {args.query!r} (limit={args.max})")
    result = agent.search_and_ingest(query)
    print()
    print(f"Returned       : {result.total_returned}")
    print(f"Ingested       : {result.ingested_count}")
    print(f"Duplicates     : {result.duplicates_skipped}")
    print(f"Verified DOIs  : {result.verification_succeeded} / {result.verification_attempted}")
    if result.per_theme_counts:
        print()
        print("Per-theme unique-paper contributions:")
        for theme, count in result.per_theme_counts.items():
            print(f"  {count:3d}  {theme}")
    print()
    print("Top hits:")
    for i, paper in enumerate(result.papers[:10], start=1):
        verified_marker = " [verified]" if paper.verified else ""
        year = paper.year or "?"
        cite = f" ({paper.citation_count} cites)" if paper.citation_count else ""
        print(f"  {i:2d}. ({year}) {paper.title[:90]}{verified_marker}{cite}")
        if paper.doi:
            print(f"       DOI: {paper.doi}")

    if args.json:
        out_path = Path(args.json)
        out_path.write_text(result.model_dump_json(indent=2))
        print(f"\nFull result written to {out_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    db = open_store(args.catalog)
    table = db.open_table("papers")
    count = table.count_rows()
    print(f"Catalog: {args.catalog}")
    print(f"Papers stored: {count}")
    if count == 0:
        return 0
    arrow = table.to_arrow()
    rows = arrow.slice(0, args.limit)
    print()
    print(f"First {min(args.limit, count)} papers:")
    titles = rows.column("title").to_pylist()
    years = rows.column("year").to_pylist()
    dois = rows.column("doi").to_pylist()
    verified = rows.column("verified").to_pylist()
    for i, (title, year, doi, ver) in enumerate(zip(titles, years, dois, verified), start=1):
        year_str = str(year) if year else "?"
        ver_str = " [v]" if ver else ""
        print(f"  {i:2d}. ({year_str}) {title[:90]}{ver_str}")
        if doi:
            print(f"       {doi}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m e2sa.agents.litreview",
        description="LitReviewAgent CLI: search literature and ingest into the LanceDB store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search Semantic Scholar and ingest results")
    search.add_argument(
        "query",
        nargs="?",
        default="",
        help="Search query string (omit when using --themes)",
    )
    search.add_argument(
        "--themes",
        default=None,
        help=(
            "Comma-separated list of focused single-concept queries. When set, "
            "the agent runs one search per theme and merges. Use this with "
            "--backend mcp for paper-search-mcp's per-platform searchers."
        ),
    )
    search.add_argument(
        "--max",
        type=int,
        default=20,
        help="Max results per query (default 20, cap 100). In themed mode, this is per theme.",
    )
    search.add_argument("--year-min", type=int, default=None)
    search.add_argument("--year-max", type=int, default=None)
    search.add_argument(
        "--catalog",
        default="data/lance",
        help="LanceDB store path (default: data/lance)",
    )
    search.add_argument(
        "--backend",
        choices=["semantic_scholar", "mcp", "default"],
        default="default",
        help=(
            "Search backend: 'semantic_scholar' (default, broad relevance-ranked), "
            "'mcp' (paper-search-mcp per-platform fan-out), or 'default'"
        ),
    )
    search.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip CrossRef DOI verification (faster but less metadata enrichment)",
    )
    search.add_argument(
        "--json",
        default=None,
        help="Optional path to write full SearchResult JSON",
    )
    search.set_defaults(func=cmd_search)

    list_cmd = sub.add_parser("list", help="List papers in the LanceDB store")
    list_cmd.add_argument("--catalog", default="data/lance")
    list_cmd.add_argument("--limit", type=int, default=10)
    list_cmd.set_defaults(func=cmd_list)

    ingest_wos = sub.add_parser(
        "ingest-wos",
        help="Parse a Web of Science plain-text export and ingest into the LanceDB store.",
    )
    ingest_wos.add_argument(
        "path",
        help="Path to the WoS Full Record plain-text export (e.g., savedrecs.txt)",
    )
    ingest_wos.add_argument(
        "--catalog",
        default="data/lance",
        help="LanceDB store path (default: data/lance)",
    )
    ingest_wos.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report only. Do not write to the store.",
    )
    ingest_wos.set_defaults(func=cmd_ingest_wos)

    review = sub.add_parser(
        "review",
        help=(
            "Full LLM-orchestrated review: decompose topic into themes, "
            "themed search, LLM relevance screening, ingest"
        ),
    )
    review.add_argument(
        "--topic",
        required=True,
        help="One-sentence research question or topic.",
    )
    review.add_argument(
        "--context-file",
        default=None,
        help="Path to a project context file (e.g., projects/spade/CLAUDE.md).",
    )
    review.add_argument(
        "--seeds",
        default=None,
        help=(
            "Path to a seed reference file (Markdown / CSV / BibTeX) of "
            "known-good papers. DOIs are extracted, enriched via CrossRef, "
            "ingested as ground truth, and used to anchor relevance screening."
        ),
    )
    review.add_argument(
        "--per-theme-limit",
        type=int,
        default=5,
        help="Max search results per theme (default 5).",
    )
    review.add_argument(
        "--max-themes",
        type=int,
        default=12,
        help="Soft cap on themes the LLM is asked to produce (default 12).",
    )
    review.add_argument(
        "--no-search",
        action="store_true",
        help=(
            "Skip theme decomposition and search; instead triage papers already "
            "in the LanceDB catalog (e.g., WoS ingests). Useful after `ingest-wos`."
        ),
    )
    review.add_argument(
        "--no-screen",
        action="store_true",
        help="Skip LLM relevance screening (keep all themed search results).",
    )
    review.add_argument(
        "--keep-irrelevant",
        action="store_true",
        help="When screening is on, keep IRRELEVANT-rated papers instead of dropping them.",
    )
    review.add_argument(
        "--backend",
        choices=["semantic_scholar", "mcp", "default"],
        default="default",
    )
    review.add_argument(
        "--catalog",
        default="data/lance",
    )
    review.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip CrossRef DOI verification.",
    )
    review.add_argument(
        "--json",
        default=None,
        help="Optional path to write the full SearchResult JSON.",
    )
    review.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    return args.func(args)


def cmd_ingest_wos(args: argparse.Namespace) -> int:
    """Parse a WoS plain-text export and ingest into the LanceDB store."""
    from e2sa.rag.store import open_store

    from .wos_ingest import ingest_wos_export

    db = open_store(args.catalog)
    print(f"Parsing WoS export: {args.path}")
    result = ingest_wos_export(db, args.path, dry_run=args.dry_run)

    if result.errors:
        for err in result.errors:
            print(f"ERROR: {err}")
        return 1

    mode = "(dry run)" if args.dry_run else ""
    print(f"\nRecords parsed        : {result.records_parsed} {mode}")
    print(f"  with DOI             : {result.records_with_doi}")
    print(f"  with WoS UID only    : {result.records_with_wos_uid}")
    print(f"  with abstract        : {result.records_with_abstract}")
    print(f"  with year            : {result.records_with_year}")
    if not args.dry_run:
        print(f"\nIngested into catalog : {result.ingested}")
        print(f"Duplicates skipped    : {result.duplicates_skipped}")

    # Preview top 5 by citation count
    from .wos_ingest import parse_wos_file

    papers = parse_wos_file(args.path)
    top = sorted(
        [p for p in papers if p.citation_count is not None],
        key=lambda p: p.citation_count or 0,
        reverse=True,
    )[:5]
    if top:
        print("\nTop 5 by citation count:")
        for i, p in enumerate(top, start=1):
            year = p.year or "?"
            cc = p.citation_count or 0
            print(f"  {i}. ({year}) {p.title[:80]} [{cc} cites]")
            if p.doi:
                print(f"     DOI: {p.doi}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from .agent import LitReviewAgent
    from .llm import AnthropicLLM
    from .seeds import load_seeds

    search_client = None
    if args.backend == "mcp":
        try:
            from .paper_search_mcp_backend import PaperSearchMCPBackend

            search_client = PaperSearchMCPBackend()
        except ImportError:
            print(
                "ERROR: paper-search-mcp not installed. Run: pip install paper-search-mcp"
            )
            return 1
    elif args.backend == "semantic_scholar":
        from .search import SemanticScholarClient

        search_client = SemanticScholarClient()

    try:
        llm = AnthropicLLM()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    context = ""
    if args.context_file:
        context = Path(args.context_file).read_text(encoding="utf-8")
        print(f"Loaded context from {args.context_file} ({len(context)} chars)")

    seeds = None
    if args.seeds:
        print(f"Loading seeds from {args.seeds}...")
        seeds = load_seeds(args.seeds)
        print(f"Loaded {len(seeds)} seed papers")
        for s in seeds[:5]:
            year = f" ({s.year})" if s.year else ""
            print(f"  - {s.title[:80]}{year}")
        if len(seeds) > 5:
            print(f"  ... and {len(seeds) - 5} more")
        print()

    agent = LitReviewAgent(
        store_path=args.catalog,
        search_client=search_client,
        verify_dois=not args.no_verify,
    )
    backend_name = type(agent.search_client).__name__
    if args.no_search:
        print("Backend: (none, --no-search mode)")
    else:
        print(f"Backend: {backend_name}")
    print(f"Topic: {args.topic!r}")
    print()

    if args.no_search:
        result = agent.do_triage_only(
            topic=args.topic,
            context=context,
            llm=llm,
            seeds=seeds,
            drop_irrelevant=not args.keep_irrelevant,
        )
        print(f"Papers triaged       : {result.total_returned}")
    else:
        result = agent.do_themed_review(
            topic=args.topic,
            context=context,
            llm=llm,
            seeds=seeds,
            per_theme_limit=args.per_theme_limit,
            max_themes=args.max_themes,
            screen=not args.no_screen,
            drop_irrelevant=not args.keep_irrelevant,
        )
        print(f"Themes generated     : {len(result.query.themes)}")
        for t in result.query.themes:
            print(f"  - {t}")
        print()
    print(f"Returned (after screen): {result.total_returned}")
    print(f"Ingested              : {result.ingested_count}")
    print(f"Duplicates            : {result.duplicates_skipped}")
    print(f"Verified DOIs         : {result.verification_succeeded} / {result.verification_attempted}")
    if result.per_theme_counts:
        print()
        print("Per-theme contributions (before screening):")
        for theme, count in result.per_theme_counts.items():
            print(f"  {count:3d}  {theme}")
    print()
    print("Top hits:")
    for i, paper in enumerate(result.papers[:15], start=1):
        rel = paper.extra.get("relevance", "")
        rel_marker = f" [{rel}]" if rel else ""
        verified_marker = " [verified]" if paper.verified else ""
        year = paper.year or "?"
        cite = f" ({paper.citation_count} cites)" if paper.citation_count else ""
        print(f"  {i:2d}. ({year}) {paper.title[:85]}{rel_marker}{verified_marker}{cite}")
        if paper.doi:
            print(f"       DOI: {paper.doi}")
        reason = paper.extra.get("relevance_reason", "")
        if reason:
            print(f"       why: {reason}")

    if args.json:
        out_path = Path(args.json)
        out_path.write_text(result.model_dump_json(indent=2))
        print(f"\nFull result written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

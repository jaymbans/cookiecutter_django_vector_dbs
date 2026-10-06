# Needed at runtime: FastMCP reads the type hints to build each tool's JSON Schema.
from datetime import date  # noqa: TC003
from typing import Annotated
from typing import Any

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from openai import OpenAIError
from pgvector.django import CosineDistance
from pydantic import Field

from cookiecutter_django_vector_dbs.search.embeddings import create_embeddings
from cookiecutter_django_vector_dbs.search.models import Document

TOPICS_URI = "documents://topics"

mcp = FastMCP(
    name="documents-search",
    instructions=(
        "Search a database of AI news articles with the search_documents tool. "
        f"The valid category names are in the {TOPICS_URI} resource; read it before "
        "filtering by category. The find_articles prompt shows the recommended workflow."
    ),
)


def _topics() -> list[str]:
    close_old_connections()
    return list(
        Document.objects.values_list("category", flat=True).distinct().order_by("category"),
    )


# --- Resource: read-only data the client can load as context -------------------


@mcp.resource(TOPICS_URI, name="topics", mime_type="application/json")
def topics() -> list[str]:
    """Every article category in the database, as a JSON list of exact names.

    Use these exact strings for search_documents' category parameter.
    """
    return _topics()


# --- Tool: an action the model decides to call ---------------------------------


@mcp.tool
def search_documents(
    query: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Natural-language description of the topic, e.g. 'AI diagnostic tools'. "
                "Do not put dates or categories here; use the other parameters."
            ),
        ),
    ],
    min_date: Annotated[
        date | None,
        Field(
            description=(
                "Exclusive lower bound on publish date, ISO YYYY-MM-DD (e.g. 2024-12-31). "
                "Must be given together with max_date."
            ),
        ),
    ] = None,
    max_date: Annotated[
        date | None,
        Field(
            description=(
                "Exclusive upper bound on publish date, ISO YYYY-MM-DD (e.g. 2026-01-01). "
                "Must be given together with min_date."
            ),
        ),
    ] = None,
    category: Annotated[
        str | None,
        Field(
            description=(
                f"Exact category name from the {TOPICS_URI} resource, e.g. 'Healthcare'. "
                "Omit to search every category."
            ),
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """Semantic search over the AI news article database; returns the 3 closest matches.

    Use this when the user asks to find, recommend, or summarize articles on a subject,
    optionally limited to a date range or a category. Lower distance means a closer match.
    """
    close_old_connections()

    if (min_date is None) != (max_date is None):
        msg = "min_date and max_date must be provided together (YYYY-MM-DD), or both omitted."
        raise ToolError(msg)

    docs = Document.objects.all()

    if min_date is not None:
        # Exclusive bounds, matching DocumentViewSet.search: articles published
        # exactly on min_date or max_date are left out.
        docs = docs.filter(published_date__gt=min_date, published_date__lt=max_date)

    if category:
        valid_topics = _topics()
        if category not in valid_topics:
            msg = f"Unknown category {category!r}. Valid categories: {', '.join(valid_topics)}."
            raise ToolError(msg)
        docs = docs.filter(category=category)

    try:
        query_embedding = create_embeddings([query])[0]
    except OpenAIError as exc:
        msg = "The embedding service is unavailable; try again shortly."
        raise ToolError(msg) from exc

    return list(
        docs.annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")
        .values(
            "id",
            "title",
            "source",
            "published_date",
            "url",
            "summary",
            "category",
            "distance",
        )[:3],
    )


# --- Prompt: a reusable template the user picks to kick off a workflow ---------


@mcp.prompt
def find_articles(
    topic: Annotated[str, Field(description="What the articles should be about.")],
    timeframe: Annotated[
        str | None,
        Field(description="Optional period in plain words, e.g. '2025' or 'last spring'."),
    ] = None,
) -> str:
    """Find and summarize the most relevant articles on a topic, the recommended way."""
    timeframe_step = (
        f"3. Convert the timeframe '{timeframe}' to dates. The bounds are exclusive, so "
        "widen by one day on each side: all of 2025 is min_date=2024-12-31, "
        "max_date=2026-01-01.\n"
        if timeframe
        else "3. No timeframe was given, so leave min_date and max_date out.\n"
    )
    return (
        f"Find articles about: {topic}\n\n"
        f"1. These are the only valid categories ({TOPICS_URI}): {', '.join(_topics())}.\n"
        "2. If exactly one category clearly matches the topic, use it. Otherwise leave "
        "category out; the semantic search handles it.\n"
        f"{timeframe_step}"
        "4. Call search_documents with a short natural-language query (no dates or "
        "category names in the query text).\n"
        "5. Answer with each article's title, source, publish date and URL, plus one "
        "sentence on why it is relevant. If nothing fits, say so; don't invent articles."
    )


class Command(BaseCommand):
    help = "Run the FastMCP server that exposes Document search as MCP tools over HTTP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            # All interfaces, so the port is reachable from outside the Docker container.
            default="0.0.0.0",  # noqa: S104
            help="Interface to bind (default: 0.0.0.0).",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8001,
            help="Port to listen on (default: 8001).",
        )

    def handle(self, *args, **options):
        mcp.run(
            transport="http",
            host=options["host"],
            port=options["port"],
            # Plain request/response: no session IDs and no SSE streams.
            stateless_http=True,
            json_response=True,
        )

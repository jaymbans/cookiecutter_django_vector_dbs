# Cookiecutter Django Vector Databases

This is a lesson on how to install a vector database within cookiecutter django.

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)

License: MIT

## Getting Started

### 1. Build and start the local stack

This project runs locally through Docker Compose, using `local.yml`. Build the images first, then start the stack:

    docker compose -f local.yml build
    docker compose -f local.yml up -d

The `postgres` service is built from the `pgvector/pgvector:pg17` image, so the `vector` Postgres extension is available out of the box — no extra setup on your machine needed.

### 2. Apply migrations

If you're starting from a fresh database, run migrations to create the schema (this is also what enables the `vector` extension in Postgres, via a `VectorExtension()` operation baked into the `search` app's initial migration):

    docker compose -f local.yml run --rm django python manage.py migrate

If you've made model changes and need a new migration file, generate one first:

    docker compose -f local.yml run --rm django python manage.py makemigrations
    docker compose -f local.yml run --rm django python manage.py migrate

### 3. Load the demo data

Create a superuser so you can authenticate against the API later:

    docker compose -f local.yml run --rm django python manage.py createsuperuser

Then load the sample articles from `ai_articles_dummy.csv`, embedding each one via OpenAI along the way:

    docker compose -f local.yml run --rm django python manage.py load_embeddings

This reads the CSV, generates a 1536-dimension embedding for each article's summary, and bulk-inserts them as `Document` rows.

### 4. Confirm the endpoints are up

If everything above ran correctly, you should have the following endpoints available at `http://localhost:8000`:

- `GET /api/documents/` — list all loaded documents
- `GET /api/documents/{id}/` — retrieve a single document
- `POST /api/documents/search/` — semantic search: embeds your query and returns the nearest documents by cosine distance
- `POST /api/auth-token/` — exchange a username/password for an auth token
- `/api/docs/` — browsable API schema (drf-spectacular)

## Using the Search Endpoint

### Via the browser

Log in as your superuser, then visit `http://localhost:8000/api/documents/search/`. Since this endpoint doesn't use a request serializer, use the **"Raw data"** tab (not the HTML form tab) to submit JSON directly, e.g.:

```json
{"query": "a sentence related to one of your articles"}
```

Hit **POST**, and the response will list the closest matching documents along with their `distance` score. Change the `query` value and resubmit to try different searches.

### Via the CLI (curl)

Since the API requires authentication, first get a token:

    curl -X POST http://localhost:8000/api/auth-token/ \
      -H "Content-Type: application/json" \
      -d '{"username": "your_username", "password": "your_password"}'

This returns `{"token": "..."}`. Use that token on the search request:

    curl -X POST http://localhost:8000/api/documents/search/ \
      -H "Content-Type: application/json" \
      -H "Authorization: Token <paste-token-here>" \
      -d '{"query": "a sentence related to one of your articles"}'

The token doesn't expire on its own, so you can reuse it for further requests without repeating the first step.

## Using the MCP Server

The same article data is also exposed as an [MCP](https://modelcontextprotocol.io) server, built with [FastMCP](https://gofastmcp.com), so an LLM can search it on its own. It runs as a separate process, the `mcp` service in `local.yml`, at `http://localhost:8001/mcp`. It's stateless and answers with plain JSON (no streaming or sessions). The code is in `cookiecutter_django_vector_dbs/search/management/commands/run_mcp_server.py`.

It exposes one of each MCP primitive:

| Primitive | Name | Who decides to use it | What it does |
|---|---|---|---|
| Tool | `search_documents` | the model | Semantic search with optional `category` and `min_date`/`max_date` filters (ISO `YYYY-MM-DD`, exclusive bounds); returns the 3 closest articles |
| Resource | `documents://topics` | the app or user | JSON list of the valid category names |
| Prompt | `find_articles(topic, timeframe?)` | the user | A ready-made instruction showing the model the right way to search |

### 1. Start it

The `mcp` service starts with the rest of the stack. If you've just pulled changes that touch `pyproject.toml` or `uv.lock`, rebuild with fresh virtualenv volumes. Otherwise the containers keep their old `.venv` and fail with `ModuleNotFoundError`:

    docker compose -f local.yml up -d --build --renew-anon-volumes

Check that it answers:

    curl -X POST http://localhost:8001/mcp \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

### 2. Connect Claude Code

    claude mcp add --transport http docs-search http://localhost:8001/mcp

Then ask Claude something like *"Any healthcare AI articles from 2025?"*. You can also attach the resource with `@docs-search:documents://topics`, or run the prompt as `/mcp__docs-search__find_articles`.

### 3. Connect an OpenAI model

An LLM never talks to an MCP server directly. A **host** program sits in the middle. It uses an **MCP client** to fetch the server's tools, hands them to the model, and runs any tool the model asks for. Claude Code is a host. The script below is a minimal one for OpenAI:

```
you ─► host (openai_host.py) ─┬─ MCP client ─► MCP server :8001 ─► Postgres
                              └─ OpenAI client ─► OpenAI
```

Save this as `openai_host.py`:

```python
"""Minimal MCP host: lets an OpenAI model use the documents-search MCP server.

Usage:
    python openai_host.py "Any healthcare AI articles from 2025?"
    python openai_host.py --prompt "AI in farming" 2025     # use the server's find_articles prompt
"""

import asyncio
import json
import os
import sys

from fastmcp import Client
from openai import OpenAI

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8001/mcp")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
MAX_TURNS = 5


# --- MCP client: talks to the MCP server --------------------------------------


def to_openai_tool(tool):
    """Translate an MCP tool definition into OpenAI's function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,  # the JSON Schema passes through unchanged
        },
    }


async def first_messages(mcp, argv):
    """Build the opening messages from the server's resource and (optionally) prompt."""
    # Resource -> context the host chooses to load into the system message.
    topics = (await mcp.read_resource("documents://topics"))[0].text
    system = {
        "role": "system",
        "content": (
            "You answer questions about a database of AI news articles using the tools "
            f"provided. Valid categories: {topics}"
        ),
    }

    # Prompt -> a template the user picks; the server returns ready-made messages.
    if argv[0] == "--prompt":
        args = {"topic": argv[1]}
        if len(argv) > 2:
            args["timeframe"] = argv[2]
        prompt = await mcp.get_prompt("find_articles", args)
        return [system] + [{"role": m.role, "content": m.content.text} for m in prompt.messages]

    return [system, {"role": "user", "content": " ".join(argv)}]


# --- Host: runs the loop between the LLM and the MCP client --------------------


async def main(argv):
    llm = OpenAI()  # reads OPENAI_API_KEY from the environment
    async with Client(MCP_URL) as mcp:
        tools = [to_openai_tool(t) for t in await mcp.list_tools()]
        messages = await first_messages(mcp, argv)

        for _ in range(MAX_TURNS):
            reply = (
                llm.chat.completions.create(model=MODEL, messages=messages, tools=tools)
                .choices[0]
                .message
            )
            messages.append(reply.model_dump(exclude_none=True))

            if not reply.tool_calls:  # no tool requested -> this is the final answer
                return reply.content

            for call in reply.tool_calls:  # the LLM asked for a tool -> run it over MCP
                args = json.loads(call.function.arguments)
                print(f"-> {call.function.name}({args})", file=sys.stderr)
                result = await mcp.call_tool(call.function.name, args, raise_on_error=False)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": "\n".join(c.text for c in result.content if c.type == "text"),
                    },
                )

    return "Stopped: too many tool calls."


if __name__ == "__main__":
    print(asyncio.run(main(sys.argv[1:])))
```

Run it from your machine. You need `fastmcp` and `openai`, which are already project dependencies, so `uv run` works. Outside this repo, use `pip install fastmcp openai`.

    export OPENAI_API_KEY=<your-key>
    uv run python openai_host.py "Any healthcare AI articles from 2025?"
    uv run python openai_host.py --prompt "AI in farming" 2025

Or run it inside the `mcp` container, which already has the key as `OPEN_AI_APIKEY`. Nothing to install or export:

    docker compose -f local.yml exec -T mcp sh -c 'OPENAI_API_KEY="$OPEN_AI_APIKEY" python - --prompt "AI in farming" 2025' < openai_host.py

Each tool call is printed as it happens (`-> search_documents({...})`), followed by the model's answer. Set `OPENAI_MODEL` to use a different model, or `MCP_URL` to point at a different server.

Note that `parameters` is the server's JSON Schema passed through unchanged. Translating the format at that one point, and passing tool results back as `tool` messages, is all the glue MCP needs: the same server works with Claude Code, OpenAI, or any other model that supports function calling.

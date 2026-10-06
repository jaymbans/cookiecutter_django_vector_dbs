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

The article data is also exposed as an [MCP](https://modelcontextprotocol.io) server, built with [FastMCP](https://gofastmcp.com), so an LLM can search it by itself. It runs as the `mcp` service in `local.yml`, at `http://localhost:8001/mcp`, and offers one of each MCP primitive:

| Primitive | Name | What it does |
|---|---|---|
| Tool | `search_documents` | Semantic search over the articles, with optional category and date filters |
| Resource | `documents://topics` | The list of valid category names |
| Prompt | `find_articles` | A ready-made instruction for searching well |

The server code is in `search/management/commands/run_mcp_server.py`.

### 1. Start it

The MCP server starts with the rest of the stack (steps 1–3 above):

    docker compose -f local.yml up -d --build --renew-anon-volumes

`--renew-anon-volumes` makes sure the containers pick up newly added Python packages.

### 2. Chat with it

    docker compose -f local.yml run --rm django python manage.py mcp_host

This starts a chat with an OpenAI model that can use the MCP server. Ask something like *"Any healthcare AI articles from 2025?"*: you'll see each tool call the model makes (`-> search_documents(...)`) and then its answer. Type `exit` to quit. It uses the same OpenAI key as the rest of the app.

The model never talks to the MCP server directly. `mcp_host` is the **host** in between: it fetches the server's tools, hands them to OpenAI, runs whichever tool the model asks for, and passes the result back. See `search/management/commands/mcp_host.py`.

### 3. Optional: use it from Claude Code

    claude mcp add --transport http docs-search http://localhost:8001/mcp

Then ask Claude your question directly.

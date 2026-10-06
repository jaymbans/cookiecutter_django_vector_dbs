import asyncio
import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from fastmcp import Client
from openai import OpenAI

MAX_TOOL_ROUNDS = 5


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


class Command(BaseCommand):
    help = "Chat with an OpenAI model that can use the documents-search MCP server."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default="http://mcp:8001/mcp",
            help="MCP server URL (default: the mcp service in local.yml).",
        )
        parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model to use.")

    def handle(self, *args, **options):
        logging.getLogger("httpx").setLevel(logging.WARNING)  # hide per-request log lines
        asyncio.run(self.chat(options["url"], options["model"]))

    async def chat(self, url, model):
        llm = OpenAI(api_key=settings.OPEN_AI_APIKEY)

        # MCP client: connect, discover the tools, and load the topics resource as context.
        async with Client(url) as mcp:
            tools = [to_openai_tool(t) for t in await mcp.list_tools()]
            topics = (await mcp.read_resource("documents://topics"))[0].text
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You answer questions about a database of AI news articles using the "
                        f"tools provided. Valid categories: {topics}"
                    ),
                },
            ]

            self.stdout.write(f"Connected to {url} with tools: {', '.join(t['function']['name'] for t in tools)}")
            self.stdout.write("Ask about the articles. Type 'exit' to quit.")

            while True:
                try:
                    question = input("\nyou> ").strip()
                except EOFError:
                    break
                if question.lower() in {"exit", "quit"}:
                    break
                if question:
                    messages.append({"role": "user", "content": question})
                    answer = await self.answer(llm, mcp, model, messages, tools)
                    self.stdout.write(f"\nassistant> {answer}")

    async def answer(self, llm, mcp, model, messages, tools):
        """Host loop: call the model, run any tools it asks for over MCP, repeat."""
        for _ in range(MAX_TOOL_ROUNDS):
            reply = (
                llm.chat.completions.create(model=model, messages=messages, tools=tools)
                .choices[0]
                .message
            )
            messages.append(reply.model_dump(exclude_none=True))

            if not reply.tool_calls:  # no tool requested -> this is the final answer
                return reply.content

            for call in reply.tool_calls:  # the model asked for a tool -> run it over MCP
                args = json.loads(call.function.arguments)
                self.stdout.write(self.style.NOTICE(f"  -> {call.function.name}({args})"))
                result = await mcp.call_tool(call.function.name, args, raise_on_error=False)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": "\n".join(c.text for c in result.content if c.type == "text"),
                    },
                )

        return "Stopped: too many tool calls in a row."

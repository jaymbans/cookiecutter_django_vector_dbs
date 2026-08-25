from django.conf import settings
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"

client = OpenAI(api_key=settings.OPEN_AI_APIKEY)


def create_embeddings(texts):
    """Embed a batch of strings via OpenAI, preserving input order."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    response_obj = response.model_dump()
    return [data["embedding"] for data in response_obj["data"]]

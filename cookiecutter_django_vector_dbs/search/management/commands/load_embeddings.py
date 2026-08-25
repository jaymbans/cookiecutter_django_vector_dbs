import csv

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import Error as DjangoDBError
from openai import OpenAIError

from cookiecutter_django_vector_dbs.search.embeddings import create_embeddings
from cookiecutter_django_vector_dbs.search.models import Document


class Command(BaseCommand):
    help = "Load articles from ai_articles_dummy.csv and embed their summaries via OpenAI."

    def create_embeddings(self, texts):
        try:
            return create_embeddings(texts)
        except OpenAIError as exc:
            msg = f"OpenAI embeddings request failed: {exc}"
            raise CommandError(msg) from exc

    def handle(self, *args, **options):
        csv_path = settings.BASE_DIR / "ai_articles_dummy.csv"

        try:
            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError as exc:
            msg = f"Could not find CSV file at {csv_path}"
            raise CommandError(msg) from exc

        self.stdout.write(f"Read {len(rows)} rows from {csv_path.name}")

        summaries = [row["summary"] for row in rows]
        embeddings = self.create_embeddings(summaries)

        try:
            documents = [
                Document(
                    title=row["title"],
                    source=row["source"],
                    published_date=row["published_date"],
                    url=row["url"],
                    summary=row["summary"],
                    category=row["category"],
                    embedding=embedding,
                )
                for row, embedding in zip(rows, embeddings, strict=True)
            ]
        except ValueError as exc:
            msg = f"Row count ({len(rows)}) and embedding count ({len(embeddings)}) don't match"
            raise CommandError(msg) from exc

        try:
            Document.objects.bulk_create(documents)
        except DjangoDBError as exc:
            msg = f"Failed to save documents to the database: {exc}"
            raise CommandError(msg) from exc

        self.stdout.write(self.style.SUCCESS(f"Created {len(documents)} documents."))

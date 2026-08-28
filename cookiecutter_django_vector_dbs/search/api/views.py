from pgvector.django import CosineDistance
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from cookiecutter_django_vector_dbs.search.embeddings import create_embeddings
from cookiecutter_django_vector_dbs.search.models import Document

from .serializers import DocumentSearchResultSerializer
from .serializers import DocumentSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    @action(detail=False, methods=["post"])
    def search(self, request):
        query = request.data.get("query", "")
        min_date = request.data.get("min_date", "")
        max_date = request.data.get("max_date", "")
        category = request.data.get("category", "")

        if not query:
            error_msg = "query is required"
            raise ValidationError(error_msg)

        date_filter_valid = min_date and max_date
        date_exists = min_date

        if date_exists and not date_filter_valid:
            error_msg = "include min and max date or neither (YYYYMMDD)"
            raise ValidationError(error_msg)

        docs = Document.objects.all()

        if date_exists:
            docs = docs.filter(published_date__gt=min_date).filter(
                published_date__lt=max_date,
            )

        if category:
            docs = docs.filter(category=category)

        query_embedding = create_embeddings([query])[0]

        docs = DocumentSearchResultSerializer(
            docs.annotate(
                distance=CosineDistance("embedding", query_embedding),
            ).order_by("distance")[:3],
            many=True,
        )

        return Response(docs.data)

    @action(detail=False, methods=["get"])
    def topics(self, request):
        distinct_topics = (
            Document.objects.values_list("category", flat=True).distinct().order_by("category")
            or []
        )

        return Response(distinct_topics)

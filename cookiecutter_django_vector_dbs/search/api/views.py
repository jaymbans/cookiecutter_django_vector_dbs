from pgvector.django import CosineDistance
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

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

        if not query:
            raise ValidationError("query is required")
        query_embedding = create_embeddings([query])[0]

        docs = DocumentSearchResultSerializer(
            Document.objects.annotate(distance=CosineDistance("embedding", query_embedding)).order_by("distance")[:3],
            many=True
        )

        return Response(docs.data)
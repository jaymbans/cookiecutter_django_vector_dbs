from rest_framework import serializers

from cookiecutter_django_vector_dbs.search.models import Document


class DocumentSerializer(serializers.ModelSerializer[Document]):
    class Meta:
        model = Document
        fields = [
            "id", 
            "title", 
            "source", 
            "published_date", 
            "url", 
            "summary", 
            "category"
            ]


class DocumentSearchResultSerializer(serializers.ModelSerializer[Document]):
    distance = serializers.FloatField(read_only=True) 

    class Meta:
        model = Document
        fields = [
            "id", 
            "title", 
            "source", 
            "published_date", 
            "url", 
            "summary", 
            "category",
            "distance",
            ]

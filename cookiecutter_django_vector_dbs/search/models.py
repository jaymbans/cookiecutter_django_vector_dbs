from django.db import models
from pgvector.django import VectorField


# Create your models here.
class Document(models.Model):
    title = models.CharField(max_length=255)
    source = models.CharField(max_length=255)
    published_date = models.DateField()
    url = models.URLField()
    summary = models.TextField()
    category = models.CharField(max_length=100)
    embedding = VectorField(dimensions=1536)

    def __str__(self) -> str:
        return self.title

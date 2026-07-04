from django.db import models

class ChatHistory(models.Model):
    query = models.TextField()
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Q: {self.query[:30]}"

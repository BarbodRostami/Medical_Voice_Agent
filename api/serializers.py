from rest_framework import serializers

class PredictSerializer(serializers.Serializer):
    x = serializers.FloatField()

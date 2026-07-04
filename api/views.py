from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import ChatHistory
import logging
logger = logging.getLogger(__name__)


@csrf_exempt
def save_chat(request):
    logger.warning(f"HOST HEADER: {request.META.get('HTTP_HOST')}")

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            q = data.get('question')
            a = data.get('answer')
            
            if q and a:
                ChatHistory.objects.create(query=q, answer=a)
                return JsonResponse({"status": "success"}, status=201)
            return JsonResponse({"status": "error", "message": "Missing data"}, status=400)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
    
    return JsonResponse({"status": "error", "message": "Only POST allowed"}, status=405)

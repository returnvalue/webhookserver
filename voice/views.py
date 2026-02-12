from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def answer(request):
    ncco = [
        {
            "action": "talk",
            "text": "Thanks for calling. Your webhook server is running.",
        }
    ]
    return JsonResponse(ncco, safe=False)


@csrf_exempt
@require_POST
def events(request):
    return HttpResponse("ok", content_type="text/plain")

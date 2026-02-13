from asgiref.sync import async_to_sync
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import event_store

try:
    from channels.layers import get_channel_layer
except ImportError:  # pragma: no cover - exercised only if channels missing
    get_channel_layer = None

EVENTS_GROUP_NAME = "view_events"


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
    event = event_store.build_event_from_request(request)
    event_store.add_event(event)
    _broadcast_message({"type": "event", "event": event})
    return HttpResponse("ok", content_type="text/plain")


@ensure_csrf_cookie
def events_page(request):
    return render(
        request,
        "voice/events.html",
        {
            "max_events": event_store.MAX_EVENTS,
        },
    )


@require_POST
def clear_events(request):
    event_store.clear_events()
    cleared_at = timezone.now().isoformat()
    _broadcast_message({"type": "cleared", "cleared_at": cleared_at})
    return JsonResponse({"status": "ok", "cleared_at": cleared_at})


def _broadcast_message(payload):
    if get_channel_layer is None:
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        EVENTS_GROUP_NAME,
        {
            "type": "broadcast.message",
            "payload": payload,
        },
    )

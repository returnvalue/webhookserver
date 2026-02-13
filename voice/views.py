import os
import re

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from vonage import Auth, Vonage
from vonage_voice.models.common import Phone
from vonage_voice.models.ncco import Talk
from vonage_voice.models.requests import CreateCallRequest, ToPhone

from . import event_store

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def home(request):
    return render(request, "voice/home.html")


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
    return JsonResponse({"status": "ok", "latest_id": event_store.latest_event_id()})


def events_list(request):
    since_id_raw = request.GET.get("since_id")
    since_id = None
    if since_id_raw:
        try:
            since_id = int(since_id_raw)
        except ValueError:
            since_id = None

    if since_id is None:
        events = event_store.list_events()
    else:
        events = event_store.list_events_since(since_id)

    return JsonResponse(
        {
            "status": "ok",
            "events": events,
            "max_events": event_store.MAX_EVENTS,
            "latest_id": event_store.latest_event_id(),
        }
    )


@ensure_csrf_cookie
def placecall(request):
    destination = ""
    message = None
    is_error = False

    if request.method == "POST":
        destination = request.POST.get("destination", "").strip()
        if not E164_RE.match(destination):
            message = "Enter a valid destination number in E.164 format (example: +15551234567)."
            is_error = True
        else:
            ok, message = _trigger_outbound_call(
                destination=destination,
            )
            is_error = not ok

    return render(
        request,
        "voice/placecall.html",
        {
            "destination": destination,
            "message": message,
            "is_error": is_error,
        },
    )


def _trigger_outbound_call(destination):
    api_key = _env_value("VONAGE_API_KEY")
    api_secret = _env_value("VONAGE_API_SECRET")
    application_id = _env_value("VONAGE_APPLICATION_ID")
    private_key = _env_value("VONAGE_PRIVATE_KEY")
    signature_secret = _env_value("VONAGE_SIGNATURE_SECRET")
    source_number = _env_value("VONAGE_SOURCE_NUMBER")
    if not source_number:
        source_number = _env_value("VONAGE_VIRTUAL_NUMBER")

    if not application_id or not private_key or not source_number:
        return (
            False,
            "Call not placed. Set VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY, and VONAGE_SOURCE_NUMBER (or VONAGE_VIRTUAL_NUMBER).",
        )

    try:
        auth = Auth(
            api_key=api_key or None,
            api_secret=api_secret or None,
            application_id=application_id,
            private_key=_resolve_private_key(private_key),
            signature_secret=signature_secret or None,
        )
        client = Vonage(auth=auth)

        destination_digits = destination.lstrip("+")
        source_digits = source_number.lstrip("+")
        request = CreateCallRequest(
            to=[ToPhone(number=destination_digits)],
            from_=Phone(number=source_digits),
            ncco=[
                Talk(
                    text="This is a simple test of the Vonage Voice API - Thank You",
                )
            ],
        )

        response = client.voice.create_call(request)
        call_uuid = getattr(response, "uuid", "unknown")
        return True, f"Call triggered to {destination}. UUID: {call_uuid}"
    except Exception as exc:  # broad on purpose to surface SDK/provider errors cleanly
        return False, f"Call failed. {exc}"


def _resolve_private_key(raw_value):
    if os.path.exists(raw_value):
        with open(raw_value, "r", encoding="utf-8") as key_file:
            return key_file.read()
    normalized = raw_value.strip().strip('"').strip("'")
    if "\\n" in normalized and "\n" not in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized


def _env_value(name):
    return os.environ.get(name, "").strip().strip('"').strip("'")

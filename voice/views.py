import os
import re
import threading

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from vonage import Auth, Vonage
from vonage_voice.models.common import Phone
from vonage_voice.models.ncco import Talk
from vonage_voice.models.requests import CreateCallRequest, ToPhone

from . import event_store
from . import placecall_request_store
from . import sms_store

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
ACTIVE_CALL_STATUSES = {"started", "ringing", "answered"}
INACTIVE_CALL_STATUSES = {"completed", "cancelled", "timeout", "failed", "busy", "rejected"}
_active_call_lock = threading.Lock()
_active_call_uuid = None


def home(request):
    return render(request, "voice/home.html")


@csrf_exempt
@require_POST
def answer(request):
    ncco = [
        {
            "action": "talk",
            "text": "Thanks for calling the webhook server.  Have a great day!",
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
def inboundsms_page(request):
    lvn = _env_value("VONAGE_VIRTUAL_NUMBER") or _env_value("VONAGE_SOURCE_NUMBER")
    return render(
        request,
        "voice/inboundsms.html",
        {
            "virtual_number": lvn,
            "max_sms": sms_store.MAX_SMS,
        },
    )


@csrf_exempt
def inboundsms_webhook(request):
    if request.method not in {"GET", "POST"}:
        return HttpResponse("Method not allowed", status=405, content_type="text/plain")

    event_store.add_event(event_store.build_event_from_request(request))
    sms_store.add_from_request(request)
    return HttpResponse("ok", content_type="text/plain")


@csrf_exempt
def delivery_webhook(request):
    if request.method not in {"GET", "POST"}:
        return HttpResponse("Method not allowed", status=405, content_type="text/plain")

    event_store.add_event(event_store.build_event_from_request(request))
    return HttpResponse("ok", content_type="text/plain")


def inboundsms_list(request):
    since_id_raw = request.GET.get("since_id")
    since_id = None
    if since_id_raw:
        try:
            since_id = int(since_id_raw)
        except ValueError:
            since_id = None

    if since_id is None:
        messages = sms_store.list_messages()
    else:
        messages = sms_store.list_messages_since(since_id)

    return JsonResponse(
        {
            "status": "ok",
            "messages": messages,
            "max_sms": sms_store.MAX_SMS,
            "latest_id": sms_store.latest_message_id(),
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

    return render(request, "voice/placecall.html", _placecall_context(destination, message, is_error))


@require_POST
def placecall_hangup(request):
    active_call = _get_active_call()
    if not active_call:
        return render(
            request,
            "voice/placecall.html",
            _placecall_context("", "No active call to hang up.", True),
        )

    ok, message = _hangup_active_call(active_call["uuid"])
    return render(
        request,
        "voice/placecall.html",
        _placecall_context("", message, not ok),
    )


@require_POST
def placecall_requests_clear(request):
    placecall_request_store.clear_requests()
    return render(
        request,
        "voice/placecall.html",
        _placecall_context("", "Cleared Place Call API request log.", False),
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
        request_payload = {
            "to": [{"type": "phone", "number": destination_digits}],
            "from": {"type": "phone", "number": source_digits},
            "ncco": [
                {
                    "action": "talk",
                    "text": "This is a simple test of the Vonage Voice API - Thank You",
                }
            ],
        }
        placecall_request_store.add_request(
            action="call",
            method="POST",
            url="https://api.nexmo.com/v1/calls",
            body=request_payload,
        )
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
        _set_active_call_uuid(call_uuid)
        return True, f"Call triggered to {destination}. UUID: {call_uuid}"
    except Exception as exc:  # broad on purpose to surface SDK/provider errors cleanly
        return False, f"Call failed. {exc}"


def _hangup_active_call(call_uuid):
    try:
        placecall_request_store.add_request(
            action="hangup",
            method="PUT",
            url=f"https://api.nexmo.com/v1/calls/{call_uuid}",
            body={"action": "hangup"},
        )
        auth = Auth(
            api_key=_env_value("VONAGE_API_KEY") or None,
            api_secret=_env_value("VONAGE_API_SECRET") or None,
            application_id=_env_value("VONAGE_APPLICATION_ID"),
            private_key=_resolve_private_key(_env_value("VONAGE_PRIVATE_KEY")),
            signature_secret=_env_value("VONAGE_SIGNATURE_SECRET") or None,
        )
        client = Vonage(auth=auth)
        client.voice.hangup(call_uuid)
        _clear_active_call_uuid()
        return True, f"Call {call_uuid} was hung up."
    except Exception as exc:  # broad on purpose to surface SDK/provider errors cleanly
        return False, f"Unable to hang up call. {exc}"


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


def _placecall_context(destination, message, is_error):
    active_call = _get_active_call()
    request_log_entries = placecall_request_store.list_requests()
    return {
        "destination": destination,
        "message": message,
        "is_error": is_error,
        "active_call": active_call,
        "has_active_call": active_call is not None,
        "request_log_entries": request_log_entries,
        "has_request_log_entries": bool(request_log_entries),
    }


def _get_active_call():
    call_uuid = _get_active_call_uuid()
    if not call_uuid:
        return None

    try:
        auth = Auth(
            api_key=_env_value("VONAGE_API_KEY") or None,
            api_secret=_env_value("VONAGE_API_SECRET") or None,
            application_id=_env_value("VONAGE_APPLICATION_ID"),
            private_key=_resolve_private_key(_env_value("VONAGE_PRIVATE_KEY")),
            signature_secret=_env_value("VONAGE_SIGNATURE_SECRET") or None,
        )
        client = Vonage(auth=auth)
        call_info = client.voice.get_call(call_uuid)
        status = _normalize_call_status(getattr(call_info, "status", ""))
        if status in INACTIVE_CALL_STATUSES:
            _clear_active_call_uuid()
            return None
        if status in ACTIVE_CALL_STATUSES:
            return {"uuid": call_uuid, "status": status}
        # Keep call actionable if provider returns an unexpected transient status.
        return {"uuid": call_uuid, "status": status or "active"}
    except Exception:
        # Do not hide hangup button if status lookup fails transiently.
        return {"uuid": call_uuid, "status": "active"}


def _set_active_call_uuid(call_uuid):
    global _active_call_uuid
    if not call_uuid:
        return
    with _active_call_lock:
        _active_call_uuid = call_uuid


def _get_active_call_uuid():
    with _active_call_lock:
        return _active_call_uuid


def _clear_active_call_uuid():
    global _active_call_uuid
    with _active_call_lock:
        _active_call_uuid = None


def _normalize_call_status(raw_status):
    if raw_status is None:
        return ""
    value = raw_status
    if hasattr(raw_status, "value"):
        value = raw_status.value
    text = str(value).strip().lower()
    if "." in text:
        text = text.split(".")[-1]
    return text

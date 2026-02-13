import json
import threading
from datetime import UTC, datetime

MAX_SMS = 100

_lock = threading.Lock()
_messages = []
_next_message_id = 1


def _read_value(source, key):
    if hasattr(source, "getlist"):
        values = source.getlist(key)
        if not values:
            return ""
        return values[0] if len(values) == 1 else values
    value = source.get(key, "")
    return value if value is not None else ""


def _payload_from_request(request):
    if request.content_type and "application/json" in request.content_type.lower():
        try:
            body = request.body.decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return request.POST if request.method == "POST" else request.GET


def add_from_request(request):
    global _next_message_id

    source = _payload_from_request(request)

    message = {
        "received_at": datetime.now(UTC).isoformat(),
        "from": _read_value(source, "msisdn") or _read_value(source, "from"),
        "to": _read_value(source, "to"),
        "text": (
            _read_value(source, "text")
            or _read_value(source, "body")
            or _read_value(source, "message")
        ),
        "message_id": _read_value(source, "messageId"),
        "network_code": _read_value(source, "network-code"),
        "type": _read_value(source, "type"),
    }

    with _lock:
        message["id"] = _next_message_id
        _next_message_id += 1
        _messages.insert(0, message)
        del _messages[MAX_SMS:]

    return message


def list_messages():
    with _lock:
        return list(_messages)


def list_messages_since(since_id):
    with _lock:
        return [msg for msg in _messages if msg["id"] > since_id]


def latest_message_id():
    with _lock:
        return _messages[0]["id"] if _messages else None


def clear_messages():
    global _next_message_id
    with _lock:
        _messages.clear()
        _next_message_id = 1

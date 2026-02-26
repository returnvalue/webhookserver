import json
import threading
from datetime import UTC, datetime

MAX_EVENTS = 100
BODY_TEXT_LIMIT = 16 * 1024

_lock = threading.Lock()
_events = []
_next_event_id = 1
SENSITIVE_HEADERS = {"authorization", "proxy-authorization"}
SENSITIVE_JSON_KEYS = {"access_token", "jwt"}


def _normalize_querydict(query_dict):
    normalized = {}
    for key in query_dict:
        values = query_dict.getlist(key)
        normalized[key] = values[0] if len(values) == 1 else values
    return normalized


def _sanitize_headers(headers):
    sanitized = {}
    for key, value in headers.items():
        if key in SENSITIVE_HEADERS and value:
            lowered = value.lower()
            if lowered.startswith("bearer "):
                sanitized[key] = "Bearer [REDACTED]"
            else:
                sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value
    return sanitized


def _redact_sensitive_json(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_JSON_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_json(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_json(item) for item in value]
    return value


def build_event_from_request(request):
    global _next_event_id

    raw_body = request.body or b""
    body_text = raw_body.decode("utf-8", errors="replace")
    body_truncated = len(body_text) > BODY_TEXT_LIMIT
    if body_truncated:
        body_text = body_text[:BODY_TEXT_LIMIT]

    content_type = request.META.get("CONTENT_TYPE")
    body_json = None
    if content_type and "application/json" in content_type.lower():
        try:
            body_json = _redact_sensitive_json(json.loads(raw_body.decode("utf-8", errors="replace")))
            body_text = json.dumps(body_json, separators=(",", ":"), ensure_ascii=False)
        except json.JSONDecodeError:
            body_json = None

    headers = _sanitize_headers({key.lower(): value for key, value in request.headers.items()})

    event = {
        "received_at": datetime.now(UTC).isoformat(),
        "method": request.method,
        "path": request.path,
        "query": _normalize_querydict(request.GET),
        "headers": headers,
        "content_type": content_type,
        "body_text": body_text,
        "body_truncated": body_truncated,
        "body_json": body_json,
        "form": _normalize_querydict(request.POST),
    }

    with _lock:
        event["id"] = _next_event_id
        _next_event_id += 1

    return event


def add_event(event):
    with _lock:
        _events.insert(0, event)
        del _events[MAX_EVENTS:]


def list_events():
    with _lock:
        return list(_events)


def list_events_since(since_id):
    with _lock:
        return [event for event in _events if event["id"] > since_id]


def latest_event_id():
    with _lock:
        return _events[0]["id"] if _events else None


def clear_events():
    with _lock:
        _events.clear()

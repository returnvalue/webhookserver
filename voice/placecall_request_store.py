import threading
from datetime import UTC, datetime

MAX_REQUESTS = 100

_lock = threading.Lock()
_requests = []
_next_id = 1


def add_request(action, method, url, body):
    global _next_id
    entry = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "action": action,
        "method": method,
        "url": url,
        "body": body,
    }
    with _lock:
        entry["id"] = _next_id
        _next_id += 1
        _requests.insert(0, entry)
        del _requests[MAX_REQUESTS:]
    return entry


def list_requests():
    with _lock:
        return list(_requests)


def clear_requests():
    with _lock:
        _requests.clear()

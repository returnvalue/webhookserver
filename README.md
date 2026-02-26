# webhookserver

A Django app for testing Vonage webhooks and simple voice flows locally.

It provides:
- A webhook event viewer (`/events`) with request payload/history capture.
- An inbound SMS viewer (`/inboundsms`) with live message history.
- A "Place Call" page (`/placecall`) to trigger and hang up outbound test calls via Vonage.

## Requirements

- Python 3.12+ (project currently appears to run on Python 3.14)
- pip

`requirements.txt` is currently empty, so install dependencies manually:

```bash
pip install django vonage vonage-voice
```

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install django vonage vonage-voice
python manage.py migrate
python manage.py runserver
```

Open: `http://127.0.0.1:8000/`

## Environment variables

This project auto-loads `.env` from the repository root.

For webhook viewing and inbound SMS pages, no Vonage credentials are required.

For outbound calling (`/placecall`), set:

- `VONAGE_APPLICATION_ID` (required)
- `VONAGE_PRIVATE_KEY` (required; file path or key contents)
- `VONAGE_SOURCE_NUMBER` (required unless `VONAGE_VIRTUAL_NUMBER` is set)
- `VONAGE_VIRTUAL_NUMBER` (optional fallback for source number and shown on SMS page)
- `VONAGE_API_KEY` (optional in current implementation)
- `VONAGE_API_SECRET` (optional in current implementation)
- `VONAGE_SIGNATURE_SECRET` (optional)

Example `.env`:

```env
VONAGE_APPLICATION_ID=your-app-id
VONAGE_PRIVATE_KEY=/absolute/path/to/private.key
VONAGE_SOURCE_NUMBER=+15550001111
VONAGE_VIRTUAL_NUMBER=+15550001111
VONAGE_API_KEY=your-api-key
VONAGE_API_SECRET=your-api-secret
VONAGE_SIGNATURE_SECRET=your-signature-secret
```

## Main routes

UI routes:
- `GET /` home page
- `GET /events` webhook event viewer
- `GET /inboundsms` inbound SMS viewer
- `GET /placecall` place-call form
- `POST /placecall` trigger call
- `POST /placecall/hangup` hang up tracked active call

Webhook/API routes:
- `POST /webhook/answer` returns NCCO talk response
- `POST /webhook/events` stores generic webhook event
- `GET /webhook/events/list` list stored events (`?since_id=<id>` supported)
- `POST /webhook/events/clear` clear event history
- `GET|POST /webhook/inbound` inbound SMS webhook alias
- `GET|POST /webhook/inboundsms` inbound SMS webhook
- `GET /webhook/inboundsms/list` list SMS history (`?since_id=<id>` supported)
- `GET|POST /webhook/delivery` delivery receipt webhook (event log only)

## Quick webhook test

Send a test event:

```bash
curl -X POST http://127.0.0.1:8000/webhook/events \
  -H "Content-Type: application/json" \
  -d '{"type":"ping","source":"local"}'
```

Send a test inbound SMS:

```bash
curl -X POST http://127.0.0.1:8000/webhook/inboundsms \
  -d "msisdn=14155550100&to=18339893850&text=hello"
```

## Running tests

```bash
python manage.py test voice
```

## Notes

- Event/SMS/request logs are in-memory and reset when the process restarts.
- The default Django SQLite database is `db.sqlite3`.
- `ALLOWED_HOSTS` already includes `localhost`, `127.0.0.1`, and `*.ngrok-free.app`.

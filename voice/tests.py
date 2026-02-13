import asyncio
import json
from unittest import skipUnless

from asgiref.sync import sync_to_async
from django.test import TestCase, TransactionTestCase

from . import event_store

try:
    from channels.testing import WebsocketCommunicator
    from webhookserver.asgi import application

    HAS_CHANNELS = True
except ImportError:
    HAS_CHANNELS = False


class EventsHttpTests(TestCase):
    def setUp(self):
        event_store.clear_events()

    def test_events_webhook_returns_ok_plain_text(self):
        response = self.client.post(
            "/webhook/events",
            data=json.dumps({"type": "ping"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_events_webhook_stores_normalized_payload(self):
        response = self.client.post(
            "/webhook/events?source=unit",
            data=json.dumps({"hello": "world"}),
            content_type="application/json",
            HTTP_X_TRACE_ID="abc123",
        )

        self.assertEqual(response.status_code, 200)
        events = event_store.list_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["method"], "POST")
        self.assertEqual(event["path"], "/webhook/events")
        self.assertEqual(event["query"], {"source": "unit"})
        self.assertEqual(event["body_json"], {"hello": "world"})
        self.assertEqual(event["headers"]["x-trace-id"], "abc123")

    def test_retention_keeps_latest_max_events(self):
        for idx in range(event_store.MAX_EVENTS + 5):
            self.client.post(
                "/webhook/events",
                data=json.dumps({"idx": idx}),
                content_type="application/json",
            )

        events = event_store.list_events()
        self.assertEqual(len(events), event_store.MAX_EVENTS)
        self.assertEqual(events[0]["body_json"], {"idx": event_store.MAX_EVENTS + 4})
        self.assertEqual(events[-1]["body_json"], {"idx": 5})

    def test_clear_events_endpoint_clears_global_store(self):
        self.client.post("/webhook/events", data="abc", content_type="text/plain")
        self.assertEqual(len(event_store.list_events()), 1)

        response = self.client.post("/webhook/events/clear")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_store.list_events(), [])

    def test_events_page_renders(self):
        response = self.client.get("/events")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Events")
        self.assertContains(response, "/ws/events")


@skipUnless(HAS_CHANNELS, "channels is not installed")
class EventsWebSocketTests(TransactionTestCase):
    def setUp(self):
        event_store.clear_events()

    def test_websocket_snapshot_event_and_cleared_messages(self):
        async def scenario():
            communicator = WebsocketCommunicator(application, "/ws/events")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            snapshot = await communicator.receive_json_from(timeout=1)
            self.assertEqual(snapshot["type"], "snapshot")
            self.assertEqual(snapshot["events"], [])
            self.assertEqual(snapshot["max_events"], event_store.MAX_EVENTS)

            post_response = await sync_to_async(self.client.post)(
                "/webhook/events",
                data=json.dumps({"kind": "call-event"}),
                content_type="application/json",
            )
            self.assertEqual(post_response.status_code, 200)

            event_message = await communicator.receive_json_from(timeout=1)
            self.assertEqual(event_message["type"], "event")
            self.assertEqual(event_message["event"]["body_json"], {"kind": "call-event"})

            clear_response = await sync_to_async(self.client.post)("/webhook/events/clear")
            self.assertEqual(clear_response.status_code, 200)

            cleared_message = await communicator.receive_json_from(timeout=1)
            self.assertEqual(cleared_message["type"], "cleared")
            self.assertIn("cleared_at", cleared_message)

            await communicator.disconnect()

        asyncio.run(scenario())

    def test_websocket_reconnect_receives_fresh_snapshot(self):
        async def scenario():
            await sync_to_async(self.client.post)(
                "/webhook/events",
                data=json.dumps({"order": 1}),
                content_type="application/json",
            )

            first = WebsocketCommunicator(application, "/ws/events")
            connected, _ = await first.connect()
            self.assertTrue(connected)
            snapshot = await first.receive_json_from(timeout=1)
            self.assertEqual(snapshot["type"], "snapshot")
            self.assertEqual(len(snapshot["events"]), 1)
            await first.disconnect()

            await sync_to_async(self.client.post)(
                "/webhook/events",
                data=json.dumps({"order": 2}),
                content_type="application/json",
            )

            second = WebsocketCommunicator(application, "/ws/events")
            connected, _ = await second.connect()
            self.assertTrue(connected)
            resnapshot = await second.receive_json_from(timeout=1)
            self.assertEqual(resnapshot["type"], "snapshot")
            self.assertEqual(resnapshot["events"][0]["body_json"], {"order": 2})
            self.assertEqual(resnapshot["events"][1]["body_json"], {"order": 1})
            await second.disconnect()

        asyncio.run(scenario())

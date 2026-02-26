import json
import os
from unittest.mock import Mock, patch

from django.test import TestCase

from . import event_store
from . import placecall_request_store
from . import sms_store
from . import views


class _EnumLikeStatus:
    def __init__(self, value):
        self.value = value


class EventsHttpTests(TestCase):
    def setUp(self):
        event_store.clear_events()
        sms_store.clear_messages()

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
            HTTP_AUTHORIZATION="Bearer super-secret-token",
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
        self.assertEqual(event["headers"]["authorization"], "Bearer [REDACTED]")

    def test_events_webhook_redacts_access_token_and_jwt_in_json_body(self):
        response = self.client.post(
            "/webhook/events",
            data=json.dumps(
                {
                    "api_key": "visible-key",
                    "access_token": "secret-access-token",
                    "nested": {"jwt": "secret-jwt"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        event = event_store.list_events()[0]
        self.assertEqual(event["body_json"]["api_key"], "visible-key")
        self.assertEqual(event["body_json"]["access_token"], "[REDACTED]")
        self.assertEqual(event["body_json"]["nested"]["jwt"], "[REDACTED]")
        self.assertIn("\"access_token\":\"[REDACTED]\"", event["body_text"])
        self.assertIn("\"jwt\":\"[REDACTED]\"", event["body_text"])

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
        self.assertContains(response, "/webhook/events/list")
        self.assertNotContains(response, "/ws/events")

    def test_events_list_without_since_id_returns_snapshot(self):
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 1}),
            content_type="application/json",
        )
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 2}),
            content_type="application/json",
        )

        response = self.client.get("/webhook/events/list")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["max_events"], event_store.MAX_EVENTS)
        self.assertEqual(payload["latest_id"], event_store.latest_event_id())
        self.assertEqual(payload["events"][0]["body_json"], {"idx": 2})
        self.assertEqual(payload["events"][1]["body_json"], {"idx": 1})

    def test_events_list_with_since_id_returns_incremental_events(self):
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 1}),
            content_type="application/json",
        )
        first_id = event_store.latest_event_id()

        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 2}),
            content_type="application/json",
        )
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 3}),
            content_type="application/json",
        )

        response = self.client.get(f"/webhook/events/list?since_id={first_id}")
        payload = response.json()
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["events"][0]["body_json"], {"idx": 3})
        self.assertEqual(payload["events"][1]["body_json"], {"idx": 2})

    def test_events_list_with_no_new_events_returns_empty_delta(self):
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 1}),
            content_type="application/json",
        )
        latest_id = event_store.latest_event_id()

        response = self.client.get(f"/webhook/events/list?since_id={latest_id}")
        payload = response.json()
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["latest_id"], latest_id)

    def test_events_list_with_invalid_since_id_returns_snapshot(self):
        self.client.post(
            "/webhook/events",
            data=json.dumps({"idx": 9}),
            content_type="application/json",
        )
        response = self.client.get("/webhook/events/list?since_id=abc")
        payload = response.json()
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["body_json"], {"idx": 9})


class HomeAndPlaceCallTests(TestCase):
    def setUp(self):
        event_store.clear_events()
        sms_store.clear_messages()
        views._clear_active_call_uuid()
        placecall_request_store.clear_requests()

    def test_home_page_renders_links(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Webhook Server")
        self.assertContains(response, "href=\"/events\"")
        self.assertContains(response, "href=\"/placecall\"")
        self.assertContains(response, "Receive SMS")
        self.assertContains(response, "href=\"/inboundsms\"")

    def test_placecall_page_renders(self):
        response = self.client.get("/placecall")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Place Call")
        self.assertContains(response, "Destination Number")
        self.assertNotContains(response, "Hang Up Active Call")
        self.assertContains(response, "Place Call API Requests")

    def test_placecall_rejects_invalid_number(self):
        response = self.client.post("/placecall", data={"destination": "555-123-4567"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid destination number in E.164 format")

    def test_placecall_requires_provider_env(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/placecall", data={"destination": "+15551234567"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Set VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY, and VONAGE_SOURCE_NUMBER"
        )

    @patch("voice.views.Vonage")
    def test_placecall_triggers_call_on_valid_input(self, mocked_vonage):
        mocked_client = Mock()
        mocked_client.voice.create_call.return_value = Mock(uuid="abc-123")
        mocked_client.voice.get_call.return_value = Mock(status="started")
        mocked_vonage.return_value = mocked_client

        with patch.dict(
            os.environ,
            {
                "VONAGE_API_KEY": "key",
                "VONAGE_API_SECRET": "secret",
                "VONAGE_APPLICATION_ID": "app-id",
                "VONAGE_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                "VONAGE_SIGNATURE_SECRET": "sig-secret",
                "VONAGE_SOURCE_NUMBER": "+15550001111",
            },
            clear=True,
        ):
            response = self.client.post("/placecall", data={"destination": "+15551234567"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Call triggered to +15551234567. UUID: abc-123")
        self.assertContains(response, "Hang Up Active Call")
        self.assertContains(response, "https://api.nexmo.com/v1/calls")
        self.assertContains(response, "POST")
        self.assertEqual(mocked_client.voice.create_call.call_count, 1)
        sent_request = mocked_client.voice.create_call.call_args.args[0]
        self.assertEqual(
            sent_request.ncco[0].text,
            "This is a simple test of the Vonage Voice API - Thank You",
        )

    @patch("voice.views.Vonage")
    def test_placecall_hangup_ends_current_active_call(self, mocked_vonage):
        mocked_client = Mock()
        mocked_client.voice.create_call.return_value = Mock(uuid="abc-123")
        mocked_client.voice.get_call.return_value = Mock(status="started")
        mocked_vonage.return_value = mocked_client

        with patch.dict(
            os.environ,
            {
                "VONAGE_API_KEY": "key",
                "VONAGE_API_SECRET": "secret",
                "VONAGE_APPLICATION_ID": "app-id",
                "VONAGE_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                "VONAGE_SIGNATURE_SECRET": "sig-secret",
                "VONAGE_SOURCE_NUMBER": "+15550001111",
            },
            clear=True,
        ):
            self.client.post("/placecall", data={"destination": "+15551234567"})
            response = self.client.post("/placecall/hangup")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "was hung up")
        self.assertContains(response, "https://api.nexmo.com/v1/calls/abc-123")
        self.assertContains(response, "PUT")
        self.assertEqual(mocked_client.voice.hangup.call_count, 1)

    @patch("voice.views.Vonage")
    def test_placecall_request_log_clear(self, mocked_vonage):
        mocked_client = Mock()
        mocked_client.voice.create_call.return_value = Mock(uuid="abc-123")
        mocked_client.voice.get_call.return_value = Mock(status="started")
        mocked_vonage.return_value = mocked_client

        with patch.dict(
            os.environ,
            {
                "VONAGE_API_KEY": "key",
                "VONAGE_API_SECRET": "secret",
                "VONAGE_APPLICATION_ID": "app-id",
                "VONAGE_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                "VONAGE_SIGNATURE_SECRET": "sig-secret",
                "VONAGE_SOURCE_NUMBER": "+15550001111",
            },
            clear=True,
        ):
            self.client.post("/placecall", data={"destination": "+15551234567"})
            response = self.client.post("/placecall/requests/clear")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cleared Place Call API request log.")
        self.assertContains(response, "No call API requests captured yet.")

    @patch("voice.views.Vonage")
    def test_placecall_shows_hangup_for_enum_like_status(self, mocked_vonage):
        mocked_client = Mock()
        mocked_client.voice.create_call.return_value = Mock(uuid="abc-123")
        mocked_client.voice.get_call.return_value = Mock(status=_EnumLikeStatus("started"))
        mocked_vonage.return_value = mocked_client

        with patch.dict(
            os.environ,
            {
                "VONAGE_API_KEY": "key",
                "VONAGE_API_SECRET": "secret",
                "VONAGE_APPLICATION_ID": "app-id",
                "VONAGE_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                "VONAGE_SIGNATURE_SECRET": "sig-secret",
                "VONAGE_SOURCE_NUMBER": "+15550001111",
            },
            clear=True,
        ):
            response = self.client.post("/placecall", data={"destination": "+15551234567"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hang Up Active Call")

    def test_inboundsms_page_renders_instructions(self):
        with patch.dict(os.environ, {"VONAGE_VIRTUAL_NUMBER": "18339893850"}, clear=True):
            response = self.client.get("/inboundsms")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inbound SMS")
        self.assertContains(response, "Send an SMS to")
        self.assertContains(response, "18339893850")
        self.assertContains(response, "it will display on this page")

    def test_inboundsms_webhook_stores_message_and_logs_event(self):
        response = self.client.post(
            "/webhook/inboundsms",
            data={
                "msisdn": "14155550100",
                "to": "18339893850",
                "text": "hello from test",
                "messageId": "abc-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

        list_response = self.client.get("/webhook/inboundsms/list")
        payload = list_response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["messages"][0]["text"], "hello from test")
        self.assertEqual(payload["messages"][0]["from"], "14155550100")
        self.assertEqual(payload["messages"][0]["to"], "18339893850")

        events = event_store.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["path"], "/webhook/inboundsms")

    def test_inbound_webhook_path_stores_message(self):
        response = self.client.post(
            "/webhook/inbound",
            data={"msisdn": "14155550100", "to": "18339893850", "text": "hello inbound alias"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

        payload = self.client.get("/webhook/inboundsms/list").json()
        self.assertEqual(payload["messages"][0]["text"], "hello inbound alias")
        self.assertEqual(event_store.list_events()[0]["path"], "/webhook/inbound")

    def test_delivery_webhook_logs_event(self):
        response = self.client.post(
            "/webhook/delivery",
            data={"messageId": "m-1", "status": "delivered", "to": "18339893850"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(event_store.list_events()[0]["path"], "/webhook/delivery")

    def test_inboundsms_list_since_id(self):
        self.client.post(
            "/webhook/inboundsms",
            data={"msisdn": "14155550100", "to": "18339893850", "text": "first"},
        )
        first_id = sms_store.latest_message_id()
        self.client.post(
            "/webhook/inboundsms",
            data={"msisdn": "14155550101", "to": "18339893850", "text": "second"},
        )

        response = self.client.get(f"/webhook/inboundsms/list?since_id={first_id}")
        payload = response.json()
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["text"], "second")

    def test_inbound_webhook_json_body_stores_message_fields(self):
        response = self.client.post(
            "/webhook/inbound",
            data=json.dumps(
                {
                    "msisdn": "19784072046",
                    "to": "18339893850",
                    "text": "this is a message with some text",
                    "messageId": "267a1412-f583-4e85-9965-77c5a0508a29",
                    "type": "text",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        payload = self.client.get("/webhook/inboundsms/list").json()
        self.assertEqual(payload["messages"][0]["from"], "19784072046")
        self.assertEqual(payload["messages"][0]["to"], "18339893850")
        self.assertEqual(payload["messages"][0]["text"], "this is a message with some text")

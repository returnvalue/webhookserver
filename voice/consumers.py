from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import event_store

EVENTS_GROUP_NAME = "view_events"


class EventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(EVENTS_GROUP_NAME, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "snapshot",
                "events": event_store.list_events(),
                "max_events": event_store.MAX_EVENTS,
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(EVENTS_GROUP_NAME, self.channel_name)

    async def broadcast_message(self, event):
        await self.send_json(event["payload"])


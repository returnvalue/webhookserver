from django.urls import path

from . import views

urlpatterns = [
    path("answer", views.answer, name="answer"),
    path("events", views.events, name="events"),
    path("events/list", views.events_list, name="events-list"),
    path("events/clear", views.clear_events, name="clear-events"),
    path("inbound", views.inboundsms_webhook, name="inbound-webhook"),
    path("delivery", views.delivery_webhook, name="delivery-webhook"),
    path("inboundsms", views.inboundsms_webhook, name="inboundsms-webhook"),
    path("inboundsms/list", views.inboundsms_list, name="inboundsms-list"),
]

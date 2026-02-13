from django.urls import path

from . import views

urlpatterns = [
    path("answer", views.answer, name="answer"),
    path("events", views.events, name="events"),
    path("events/list", views.events_list, name="events-list"),
    path("events/clear", views.clear_events, name="clear-events"),
]

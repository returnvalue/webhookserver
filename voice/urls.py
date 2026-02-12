from django.urls import path

from . import views

urlpatterns = [
    path("answer", views.answer, name="answer"),
    path("events", views.events, name="events"),
]

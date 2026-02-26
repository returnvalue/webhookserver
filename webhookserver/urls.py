from django.contrib import admin
from django.urls import include, path
from voice import views as voice_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", voice_views.home, name="home"),
    path("events", voice_views.events_page, name="view-events"),
    path("inboundsms", voice_views.inboundsms_page, name="inboundsms-page"),
    path("placecall", voice_views.placecall, name="placecall"),
    path("placecall/hangup", voice_views.placecall_hangup, name="placecall-hangup"),
    path("placecall/requests/clear", voice_views.placecall_requests_clear, name="placecall-requests-clear"),
    path('webhook/', include('voice.urls')),
]

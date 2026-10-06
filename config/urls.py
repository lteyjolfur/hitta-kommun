from django.urls import include, path

urlpatterns = [
    path("", include("finder.urls")),
]

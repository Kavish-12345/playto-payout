from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

urlpatterns = [
    path('api/v1/', include('payouts.urls')),
]

urlpatterns += staticfiles_urlpatterns()
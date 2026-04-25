from django.urls import path
from .views import PayoutListCreateView, MerchantBalanceView, MerchantListView

urlpatterns = [
    path('merchants/', MerchantListView.as_view()),
    path('merchants/<int:merchant_id>/balance/', MerchantBalanceView.as_view()),
    path('payouts/', PayoutListCreateView.as_view()),
]
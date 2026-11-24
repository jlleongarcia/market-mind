from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import api_root, home, password_change_required

admin.site.site_header = "Market Mind Administration"
admin.site.site_title = "Market Mind Admin"
admin.site.index_title = "Portfolio Management"

urlpatterns = [
    path('', home, name='home'),
    path('api/', api_root, name='api-root'),
    path('admin/', admin.site.urls),

    # Authentication
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        redirect_authenticated_user=True
    ), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('password-change-required/', password_change_required, name='password_change_required'),

    # Google OAuth
    path('oauth/', include('allauth.urls')),

    # Account management (registration, profile, password)
    path('account/', include('research.urls')),

    # Portfolio management
    path('portfolio/', include('portfolio.urls')),

    # Wishlist + alerts
    path('alerts/', include('alerts.urls')),

    # JWT
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

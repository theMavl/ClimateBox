"""ClimateBox URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# Serializers define the API representation.


from django.conf import settings
from django.conf.urls import url, include
from django.contrib import admin
#from django.urls import path
from django.utils.crypto import get_random_string
from rest_framework import routers
from rest_framework.documentation import include_docs_urls
import django.contrib.auth.views as auth_views

from ClimateBox.settings import HUB_SECRET_KEY_LENGTH
from hub import views

# Secret key for device registration

settings.hub_secret_key = get_random_string(length=HUB_SECRET_KEY_LENGTH).upper()

router = routers.DefaultRouter()
router.register(r'readouts', views.ReadoutViewSet)
router.register(r'devices', views.DeviceViewSet)
router.register(r'alerts', views.AlertViewSet)

urlpatterns = [
    url(r'^accounts/', include('django.contrib.auth.urls')),
    #url(r'^login/$', auth_views.login, name='login'),
    #url(r'^logout/$', auth_views.logout, name='logout'),
    #url(r'^logout/$', auth_views.logout, {'next_page': '/'}, name='logout'),
    url(r'^$', views.index, name='index'),
    #path('admin/', admin.site.urls),
    #path('hub/', include('hub.urls')),
    url(r'^admin/', admin.site.urls),
    url(r'^hub/', include('hub.urls')),
    url(r'^api/', include(router.urls)),
    #url(r'^', include('rest_framework.urls', namespace='rest_framework')),
    url('^api/secret_key', views.secret_key),
    url(r'^docs/', include_docs_urls(title='ClimateBox API', public=False)),
    url('^debug', views.debug_interface),

]

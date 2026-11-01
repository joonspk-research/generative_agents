"""frontend_server URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
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
from django.conf.urls import include, url
from django.urls import path
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView

from translator import views as translator_views
from translator import dashboard

urlpatterns = [
    url(r'^$', translator_views.landing, name='landing'),
    url(r'^simulator_home$', translator_views.home, name='home'),
    url(r'^dashboard/?$', dashboard.dashboard, name='dashboard'),
    url(r'^dashboard/state/$', dashboard.dashboard_state, name='dashboard_state'),
    url(r'^dashboard/log/$', dashboard.dashboard_log, name='dashboard_log'),
    url(r'^dashboard/usage/$', dashboard.dashboard_usage, name='dashboard_usage'),
    url(r'^dashboard/run/(?P<sim>[\w-]+)/$', dashboard.dashboard_run, name='dashboard_run'),
    url(r'^dashboard/command/$', dashboard.dashboard_command, name='dashboard_command'),
    url(r'^dashboard/launch/$', dashboard.dashboard_launch, name='dashboard_launch'),
    url(r'^dashboard/settings/$', dashboard.dashboard_settings, name='dashboard_settings'),
    # Common misspellings of the simulator page (incl. trailing slash).
    url(r'^(?:simulation_home|simulator_home/|simulation_home/)$',
        RedirectView.as_view(pattern_name='home', permanent=False)),
    url(r'^demo/(?P<sim_code>[\w-]+)/(?P<step>[\w-]+)/(?P<play_speed>[\w-]+)/$', translator_views.demo, name='demo'),
    url(r'^replay/(?P<sim_code>[\w-]+)/(?P<step>[\w-]+)/$', translator_views.replay, name='replay'),
    url(r'^replay_persona_state/(?P<sim_code>[\w-]+)/(?P<step>[\w-]+)/(?P<persona_name>[\w-]+)/$', translator_views.replay_persona_state, name='replay_persona_state'),
    url(r'^process_environment/$', translator_views.process_environment, name='process_environment'),
    url(r'^update_environment/$', translator_views.update_environment, name='update_environment'),
    url(r'^path_tester/$', translator_views.path_tester, name='path_tester'),
    url(r'^path_tester_update/$', translator_views.path_tester_update, name='path_tester_update'),
    path('admin/', admin.site.urls),
]

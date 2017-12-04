from django.conf.urls import include, url
from django.conf import settings
from django.contrib import admin
from wagtail.wagtailadmin import urls as wagtailadmin_urls
from wagtail.wagtaildocs import urls as wagtaildocs_urls
from wagtail.wagtailcore import urls as wagtail_urls

from wagtail_patches.views.other import login, logout

urlpatterns = [
    url(r'^django-admin/', include(admin.site.urls[:2], namespace=admin.site.name)),

    # We override the login form with our own version to ensure that users cannot log in to a Site which they
    # are not a member of.
    url(r'^admin/login/$', login, name='wagtailadmin_login'),
    # We override the logout view so it'll redirect to the homepage instead of the login form.
    url(r'^admin/logout/$', logout, name='wagtailadmin_logout'),
    url(r'^admin/', include(wagtailadmin_urls)),

    url(r'^documents/', include(wagtaildocs_urls)),

    url(r'', include(wagtail_urls))
]

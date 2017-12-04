from django.conf.urls import url

from ..views import users

app_name = 'wagtailusers_users'
urlpatterns = [
    url(r'^$', users.index, name='index'),
    url(r'^add/$', users.create, name='add'),
    url(r'^add_local/$', users.create_local, name='add_local'),
    url(r'^([^/]+)/$', users.edit, name='edit'),
    url(r'^remove_ldap_user/(\d+)/$', users.remove_ldap_user, name='remove_ldap_user'),
    url(r'^reset_password/([^/]+)/$', users.admin_reset_password, name='admin_reset_password'),
]

from django.conf.urls import include, url
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.utils.html import format_html
from wagtail.wagtailcore import hooks

from .urls import users, groups


@hooks.register('register_admin_urls')
def register_admin_urls():
    """
    This function overrides Wagtail's built-in /admin/users/* URLs with our own. We require significant changes to
    the User and Group editing workflows to support our multitenant functionality.
    """
    return [
        url(r'^users/', include(users)),
        url(r'^groups/', include(groups)),
    ]


@hooks.register('insert_global_admin_css')
def global_admin_css():
    """
    Add some custom CSS for our patched/replaced forms.
    """
    return format_html('<link rel="stylesheet" href="{}">', static('wagtail_patches/css/admin.css'))

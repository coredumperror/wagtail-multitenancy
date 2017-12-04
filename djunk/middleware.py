import re
from django.conf import settings
from django.http.response import HttpResponsePermanentRedirect
from django.utils.http import urlencode
from crequest.middleware import CrequestMiddleware
try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object


def get_current_request(default=None):
    """
    Returns the current request. You can optonally pass in a dummy request object to act as the default if there is no
    current request, e.g. when get_current_request() is called during a manage.py command.

    2017-07-24: This function now uses django-crequest instead of GlobalRequestMiddleware, and accepts a default arg.
    """
    return CrequestMiddleware.get_request(default)


def get_current_user(default=None):
    """
    Returns the user responsible for the current request.

    2017-07-24: This function now uses django-crequest instead of GlobalRequestMiddleware, and accepts a default arg.
    """
    try:
        return get_current_request().user
    except AttributeError:
        # There's no current request to grab a user from.
        return default


class BindViewDataToRequestMiddleware(MiddlewareMixin):
    """
    Binds data about the view being served by this request into the request object.
    Useful for cache tagging.

    USEAGE NOTE: Always add this as the very first middleware in the MIDDLEWARE_CLASSES array. Otherwise,
    request.view_data['view_name'] will not be set correctly.
    """

    def process_view(self, request, view, view_args, view_kwargs):
        request.view_data = {
            'callback': view,
            'args': view_args,
            'kwargs': view_kwargs,
            'view_name': view.func_name,
            # Since we name our namepsaces the same as our apps, we can use it as the app name if app_name isn't set.
            'app_name': request.resolver_match.app_name or request.resolver_match.namespace,
        }


class SlashMiddleware(MiddlewareMixin):
    """
    SlashMiddleware reads from the SLASHED_PATHS setting to determine which URLs to redirect from e.g. /page/ to /page
    (for aesthetics), and which to redirect from e.g. /admin to /admin/ (for hardcoded URLs that require end-slashes).

    SLASHED_PATHS must be a list of strings that start with a slash but DON'T end with one, e.g. '/admin'.

    This middleware must go first in the MIDDLEWARE_CLASSES setting. You should remove
    django.middleware.common.CommonMiddleware, as its functionality conflicts with SlashMiddleware.

    You must also set:
    APPEND_SLASH = False
    WAGTAIL_APPEND_SLASH = False
    They will conflict with SlashMiddleware if they are left with their default values.
    """

    def process_request(self, request):
        """
        Redirects all unslashed paths that match the SLASHED_PATHS setting to their slashed version.
        Redirects all slashed paths that don't match the SLASHED_PATHS setting to their slashless version.
        """
        # For some dumb reason, str.startswith() ONLY accepts tuples of strings.
        # Thus, we cast to tuple to allow our users to use any sequence type for SLASHED_PATHS.
        slashed_paths = tuple(getattr(settings, 'SLASHED_PATHS', []))

        if request.path.startswith(slashed_paths) and not request.path.endswith('/'):
            # Redirect to slashed versions.
            url = request.path + '/'
            if request.GET:
                url += '?{}'.format(urlencode(request.GET, True))
            return HttpResponsePermanentRedirect(url)
        elif (not request.path.startswith(slashed_paths) and request.path.endswith('/') and not request.path == '/'):
            # Redirect to unslashed versions.
            url = request.path[:-1]
            if request.GET:
                url += '?{}'.format(urlencode(request.GET, True))
            return HttpResponsePermanentRedirect(url)

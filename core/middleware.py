from __future__ import absolute_import

import threading
from collections import defaultdict
from crequest.middleware import CrequestMiddleware
from django.core.exceptions import MiddlewareNotUsed
from django.utils.cache import add_never_cache_headers
from django.contrib import messages
from django.contrib.auth import logout
from django.http.response import HttpResponsePermanentRedirect, HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import urlencode
from wagtail.wagtailcore.models import Site

from core.utils import match_site_to_request, user_is_member_of_site, MissingHostException
from core.logging import logger


class MultitenantSiteMiddleware(MiddlewareMixin):

    def process_request(self, request):
        """
        Set request.site to the Site object responsible for handling this request. Wagtail's version of this
        middleware only looks at the Sites' hostnames. Ours must also consider the Sites' lists of aliases.

        This middleware also denies access to users who have valid accounts, but aren't members of the current Site.
        """
        try:
            match_type, request.site = match_site_to_request(request)
        except Site.DoesNotExist:
            try:
                hostname = request.META['HTTP_HOST'].split(':')[0]
            except KeyError:
                hostname = None
            logger.warning('site.does_not_exist', hostname=hostname)
            request.site = None
        except MissingHostException:
            # If no hostname was specified, we return a 400 error. This should really only happen during tests.
            return HttpResponseBadRequest()
        else:
            # When a user visits an admin page via an alias or a non-https URL, we need to redirect them to the https
            # version of the Site's canonical domain (so the SSL cert will work).
            if request.path.startswith('/admin/') and (match_type == 'alias' or not request.is_secure()):
                url = 'https://{}{}'.format(request.site.hostname, request.path)
                if request.GET:
                    url += '?{}'.format(urlencode(request.GET, True))
                return HttpResponsePermanentRedirect(url)

            # Non-superusers are not allowed to be logged in to Sites they aren't members of.
            # This will NOT log them out of any site besides request.site.
            if (
                not request.user.is_anonymous and
                not request.user.is_superuser and
                not user_is_member_of_site(request.user, request.site)
            ):
                messages.error(request, 'Invalid credentials.')
                logger.warning(
                    'auth.site.browse.user_not_member', username=request.user.username, site=request.site.hostname
                )
                logout(request)


class MultitenantCrequestMiddleware(CrequestMiddleware):

    def __init__(self, get_response=None):
        # Skip this middleware if the middleware chain has already run at least once.
        if MiddlewareIterationCounter.get_iteration_count() >= 1:
            raise MiddlewareNotUsed
        super(MultitenantCrequestMiddleware, self).__init__(get_response)


class MiddlewareIterationCounter(object):
    """
    This middleware exists to prevent problems with Wagtail Page previews. wagtailcore.models.Page.dummy_request()
    re-executes the entire middleware chain, which middleware isn't written to expect. For example, CrequestMiddleware
    only expects to ever run process_response() once per thread, which is why it assumes it's safe to delete the stored
    request when it runs. But since the middleware chain gets run twice during a preview, it deletes the current
    thread's stored request before the request cycle is actually finished.

    By counting the interations of the middleware chain, we can subclass problematic middleware to make them exclude
    themselves from subsequent iterations.
    """

    _iterations = defaultdict(int)

    def __init__(self, get_response=None):
        self.get_response = get_response

    def __call__(self, request):
        current_thread = threading.current_thread()
        # Increment the current thread's interation counter on ingress.
        self._iterations[current_thread] += 1
        response = self.get_response(request)
        # Decrement the current thread's interation counter on egress.
        self._iterations[current_thread] -= 1
        # If we're down to 0 interations, delete the counter to avoid a memory leak.
        if self._iterations[current_thread] == 0:
            del self._iterations[current_thread]
        return response

    @classmethod
    def get_iteration_count(cls):
        """
        Returns the iteration count for the current thread.
        Since cls._iterations is a defaultdict, this can safely be called before the first increment, which returns 0.
        """
        return cls._iterations[threading.current_thread()]

from mock import patch
from django.test import TestCase
from django.core.handlers.wsgi import WSGIRequest
from django.utils.six import StringIO
from django.contrib.auth import get_user_model
from django.test.client import RequestFactory
from wagtail.wagtailcore.models import Site, Page
from wagtail_patches.monkey_patches import get_explorer_pages
from wagtail.wagtailadmin.views.home import RecentEditsPanel

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin


class TestCrossSitePages(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_cross_site_users()
        cls.wagtail_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'wagtail.flint.oursites.com',
        })

    def test_recent_edits_shows_only_current_site_pages(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        response = RecentEditsPanel(request)

        for edit in response.last_edits:
            self.assertTrue("Test" not in edit[1].title)

    @patch('wagtail_patches.monkey_patches.get_current_request')
    def test_explorer_shows_only_current_site_pages(self, request_mock):
        dummy_values = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '',
            'SERVER_NAME': '',
            'SERVER_PORT': '',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_HOST': '',
            'wsgi.version': (1, 0),
            'wsgi.input': StringIO(),
            'wsgi.errors': StringIO(),
            'wsgi.url_scheme': '',
            'wsgi.multithread': True,
            'wsgi.multiprocess': True,
            'wsgi.run_once': False,
        }
        request_return = WSGIRequest(dummy_values)
        request_return.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        request_mock.return_value = request_return

        user = get_user_model().objects.get(username='wagtail_admin')

        pages = get_explorer_pages(user)
        bad_page = Page.objects.get(title='Test Flint Homepage')

        self.assertTrue(bad_page not in pages)

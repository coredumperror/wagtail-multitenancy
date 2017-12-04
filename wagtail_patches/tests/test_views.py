from __future__ import absolute_import, unicode_literals

from django.urls import reverse
from django.http.response import HttpResponseRedirect
from django.test import TestCase

from core.tests.utils import SecureClientMixin, MultitenantSiteTestingMixin
from our_sites.models.settings import Alias


class MiddlewareTest(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()

    def test_logout_redirects_to_canonical_homepage_when_no_other_option_available(self):
        self.login(self.superuser.username)
        response = self.client.get(reverse('wagtailadmin_logout'), HTTP_HOST=self.wagtail_site.hostname)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, 'http://{}'.format(self.wagtail_site.hostname))

    def test_logout_redirects_to_non_admin_referer(self):
        self.login(self.superuser.username)
        referer = 'http://www.google.com'
        response = self.client.get(
            reverse('wagtailadmin_logout'), HTTP_HOST=self.wagtail_site.hostname, HTTP_REFERER=referer
        )
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, referer)

        referer = 'http://wagtail.oursites.com/admin/'
        response = self.client.get(
            reverse('wagtailadmin_logout'), HTTP_HOST=self.wagtail_site.hostname, HTTP_REFERER=referer
        )
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, 'http://{}'.format(self.wagtail_site.hostname))

    def test_logout_redirects_to_solo_alias(self):
        self.login(self.superuser.username)
        alias = 'blah.oursites.com'
        self.wagtail_site.settings.aliases.add(Alias(domain=alias))
        self.wagtail_site.settings.save()
        response = self.client.get(reverse('wagtailadmin_logout'), HTTP_HOST=self.wagtail_site.hostname)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, 'http://{}'.format(alias))

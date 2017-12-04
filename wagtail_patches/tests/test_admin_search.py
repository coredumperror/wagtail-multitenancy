from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command
from with_asserts.mixin import AssertHTMLMixin
from bs4 import BeautifulSoup as bs

from core.tests.utils import SecureClientMixin, MultitenantSiteTestingMixin, DummyFile


class TestAdminSearch(SecureClientMixin, TestCase, AssertHTMLMixin, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()
        call_command('update_index', stdout=DummyFile())

    def test_admin_search_shows_only_current_site_pages(self):
        self.login(self.wagtail_admin.username)
        response = self.client.get(
            reverse('wagtailadmin_pages:search'),  {'q': 'Flint'}, HTTP_HOST=self.wagtail_site.hostname
        )
        # We use beautifulsoup to prettify the string because the test client distorts the whitespace in the
        # response enough to make the css selectors fail
        prettystring = bs(response.content, "lxml").prettify()

        with self.assertHTML(prettystring, 'table[class="listing "] tr[class=" "]') as listing:
            self.assertEqual(len(listing), 1)
            self.assertFalse("Test" in listing[0].findtext('td/h2/a'))

    def test_admin_search_greys_out_unexplorable_parents(self):
        self.login(self.wagtail_admin.username)
        response = self.client.get(
            reverse('wagtailadmin_pages:search'),  {'q': 'Flint'}, HTTP_HOST=self.wagtail_site.hostname
        )
        # We use beautifulsoup to prettify the string because the test client distorts the whitespace in the
        # response enough to make the css selectors fail
        prettystring = bs(response.content, "lxml").prettify()

        with self.assertHTML(prettystring, 'table[class="listing "] tr[class=" "] td[class="parent"]') as listing:
            self.assertEqual(len(listing), 1)
            self.assertIsNone(listing[0].find('a'))
            self.assertEqual('Root', listing[0].text.strip())

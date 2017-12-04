from django.urls import reverse
from django.test import TestCase

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin


class TestMenuItemAndViewPermissions(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):
    # NOTE: We use 'wagtailsites:add' because we took over the wagtailsites ViewSet, which determines the name of
    # the view we want.

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()

    def login_admin(self):
        """ Log in as a user with permission to access the admin. """
        self.login(self.wagtail_admin.username)

    def login_superuser(self):
        """ Log in as a superuser. """
        self.login(self.superuser.username)

    ############
    # TESTS
    ############

    def test_non_superuser_gets_302_and_permission_error_from_view(self):
        self.login_admin()
        response = self.client.get(reverse('wagtailsites:add'), HTTP_HOST=self.wagtail_site.hostname)
        self.assert_permission_denied_redirect(response)

    def test_superuser_gets_form_from_view(self):
        self.login_superuser()
        response = self.client.get(reverse('wagtailsites:add'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create a New Site')
        self.assertContains(response, 'Subdomain')
        self.assertContains(response, 'Site Name')

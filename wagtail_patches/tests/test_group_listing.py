from django.urls import reverse
from django.test import TestCase
from with_asserts.mixin import AssertHTMLMixin

from core.tests.utils import get_text_contents_from_selection, MultitenantSiteTestingMixin, SecureClientMixin


class TestGroupListingPage(SecureClientMixin, TestCase, AssertHTMLMixin, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()

    ############
    # TESTS
    ############

    def test_superuser_sees_all_groups_and_full_group_names(self):
        self.login('superuser')
        response = self.client.get(reverse('wagtailusers_groups:index'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th') as table_headers:
            self.assertEqual(get_text_contents_from_selection(table_headers), ['Name'])

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # By default, the listing should be in name order:
            self.assertEqual(
                get_text_contents_from_selection(names),
                [
                    'test.flint.oursites.com Admins',
                    'test.flint.oursites.com Editors',
                    'wagtail.flint.oursites.com Admins',
                    'wagtail.flint.oursites.com Editors',
                ]
            )

    def test_wagtail_admin_sees_only_wagtail_groups_with_short_names(self):
        self.login('wagtail_admin')
        response = self.client.get(reverse('wagtailusers_groups:index'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing td.title') as names:
            self.assertEqual(get_text_contents_from_selection(names), ['Admins', 'Editors'])

    def test_wagtail_editor_gets_redirected_with_permission_denied_message(self):
        self.login('wagtail_editor')

        # Confirm that unpriviledged users get redirected back to admin home.
        response = self.client.get(reverse('wagtailusers_groups:index'), HTTP_HOST=self.wagtail_site.hostname)
        self.assert_permission_denied_redirect(response)

    def test_test_admin_sees_only_test_groups_with_short_names(self):
        self.login('test_admin')
        response = self.client.get(reverse('wagtailusers_groups:index'), HTTP_HOST=self.test_site.hostname)

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # By default, the listing should be in last_name, first_name order:
            self.assertEqual(get_text_contents_from_selection(names), ['Admins', 'Editors'])

    def test_ordering(self):
        self.login('superuser')
        response = self.client.get(reverse('wagtailusers_groups:index'), HTTP_HOST=self.wagtail_site.hostname)

        # On the unsorted page, the sort links should point to the default sorting URLs.
        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            # The list is ordered by name by default, so the normal ordering link should reverse that.
            self.assertTrue(sort_links[0].attrib['href'].endswith('?ordering=-name'))

        # Go to the name reverse-sorted page.
        response = self.client.get(
            reverse('wagtailusers_groups:index') + '?ordering=-name', HTTP_HOST=self.wagtail_site.hostname
        )

        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            self.assertTrue(sort_links[0].attrib['href'].endswith('groups/'))

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # The listing should be in reverse name order:
            self.assertEqual(
                get_text_contents_from_selection(names),
                [
                    'wagtail.flint.oursites.com Editors',
                    'wagtail.flint.oursites.com Admins',
                    'test.flint.oursites.com Editors',
                    'test.flint.oursites.com Admins',
                ]
            )

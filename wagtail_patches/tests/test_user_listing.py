from django.urls import reverse
from django.test import TestCase
from with_asserts.mixin import AssertHTMLMixin
from testfixtures import compare

from core.tests.utils import get_text_contents_from_selection, MultitenantSiteTestingMixin, SecureClientMixin


class TestUserListingPage(SecureClientMixin, TestCase, AssertHTMLMixin, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()

    ############
    # TESTS
    ############

    def test_superuser_sees_all_users_and_full_group_names(self):
        self.login('superuser')
        response = self.client.get(reverse('wagtailusers_users:index'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th') as table_headers:
            self.assertEqual(get_text_contents_from_selection(table_headers), ['Name', 'Username', 'Groups', 'Status'])

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # By default, the listing should be in last_name, first_name order:
            self.assertEqual(
                get_text_contents_from_selection(names),
                [
                    'Local Wagtail Admin',
                    'Test Admin',
                    'Wagtail Admin',
                    'Local Wagtail Editor',
                    'Wagtail Editor',
                    'Super User',
                ]
            )

        with self.assertHTML(response.content, 'table.listing td.username') as usernames:
            self.assertEqual(
                get_text_contents_from_selection(usernames),
                [
                    'wagtail.flint.oursites.com-wagtail_admin_local',
                    'test_admin',
                    'wagtail_admin',
                    'wagtail.flint.oursites.com-wagtail_editor_local',
                    'wagtail_editor',
                    'superuser'
                ]
            )

        with self.assertHTML(response.content, 'table.listing td.groups') as group_lists:
            compare(get_text_contents_from_selection(group_lists), [
                'wagtail.flint.oursites.com Admins',
                'test.flint.oursites.com Admins test.flint.oursites.com Editors',
                'wagtail.flint.oursites.com Admins',
                'wagtail.flint.oursites.com Editors',
                'wagtail.flint.oursites.com Editors',
                'Superusers'
            ])

    def test_wagtail_admin_sees_only_wagtail_users_with_short_group_names(self):
        self.login('wagtail_admin')
        response = self.client.get(reverse('wagtailusers_users:index'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th') as table_headers:
            self.assertEqual(get_text_contents_from_selection(table_headers), ['Name', 'Username', 'Groups', 'Status'])

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # By default, the listing should be in last_name, first_name order:
            self.assertEqual(get_text_contents_from_selection(names), ['Local Wagtail Admin', 'Wagtail Admin', 'Local Wagtail Editor', 'Wagtail Editor'])

        with self.assertHTML(response.content, 'table.listing td.username') as usernames:
            compare(get_text_contents_from_selection(usernames), [
                'wagtail_admin_local',
                'wagtail_admin',
                'wagtail_editor_local',
                'wagtail_editor'])

        with self.assertHTML(response.content, 'table.listing td.groups') as group_lists:
            self.assertEqual(get_text_contents_from_selection(group_lists), ['Admins', 'Admins', 'Editors', 'Editors'])

    def test_wagtail_editor_gets_redirected_with_permission_denied_message(self):
        self.login('wagtail_editor')

        # Confirm that unpriviledged users get redirected back to admin home.
        response = self.client.get(reverse('wagtailusers_users:index'), HTTP_HOST=self.wagtail_site.hostname)
        self.assert_permission_denied_redirect(response)

    def test_test_admin_sees_only_test_users_with_short_group_names(self):
        self.login('test_admin')
        response = self.client.get(reverse('wagtailusers_users:index'), HTTP_HOST=self.test_site.hostname)

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # By default, the listing should be in last_name, first_name order:
            self.assertEqual(get_text_contents_from_selection(names), ['Test Admin'])

        with self.assertHTML(response.content, 'table.listing td.username') as usernames:
            self.assertEqual(get_text_contents_from_selection(usernames), ['test_admin'])

        with self.assertHTML(response.content, 'table.listing td.groups') as group_lists:
            self.assertEqual(get_text_contents_from_selection(group_lists), ['Admins Editors'])

    def test_ordering(self):
        self.login('superuser')
        response = self.client.get(reverse('wagtailusers_users:index'), HTTP_HOST=self.wagtail_site.hostname)

        self.assertEqual(response.status_code, 200)
        # On the unsorted page, the sort links should point to the default sorting URLs.
        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            # The list is ordered by name by default, so the normal ordering link should reverse that.
            self.assertTrue(sort_links[0].attrib['href'].endswith('?ordering=-name'))
            self.assertTrue(sort_links[1].attrib['href'].endswith('?ordering=username'))

        # Go to the name reverse-sorted page.
        response = self.client.get(
            reverse('wagtailusers_users:index') + '?ordering=-name', HTTP_HOST=self.wagtail_site.hostname
        )

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            self.assertTrue(sort_links[0].attrib['href'].endswith('users/'))
            self.assertTrue(sort_links[1].attrib['href'].endswith('?ordering=username'))

        with self.assertHTML(response.content, 'table.listing td.title') as names:
            # The listing should be in reverse last_name, first_name order:
            compare(
                get_text_contents_from_selection(names),
                [
                    'Super User',
                    'Wagtail Editor',
                    'Local Wagtail Editor',
                    'Wagtail Admin',
                    'Test Admin',
                    'Local Wagtail Admin'
                ]
            )

        # Go to the username forward-sorted page.
        response = self.client.get(
            reverse('wagtailusers_users:index') + '?ordering=username', HTTP_HOST=self.wagtail_site.hostname
        )

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            self.assertTrue(sort_links[0].attrib['href'].endswith('?ordering=name'))
            self.assertTrue(sort_links[1].attrib['href'].endswith('?ordering=-username'))

        with self.assertHTML(response.content, 'table.listing td.username') as usernames:
            compare(
                get_text_contents_from_selection(usernames),
                [
                    'superuser',
                    'test_admin',
                    'wagtail.flint.oursites.com-wagtail_admin_local',
                    'wagtail.flint.oursites.com-wagtail_editor_local',
                    'wagtail_admin',
                    'wagtail_editor',
                ]
            )

        # Go to the username reverse-sorted page.
        response = self.client.get(
            reverse('wagtailusers_users:index') + '?ordering=-username', HTTP_HOST=self.wagtail_site.hostname
        )

        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'table.listing th a') as sort_links:
            self.assertTrue(sort_links[0].attrib['href'].endswith('?ordering=name'))
            self.assertTrue(sort_links[1].attrib['href'].endswith('users/'))

        with self.assertHTML(response.content, 'table.listing td.username') as usernames:
            compare(
                get_text_contents_from_selection(usernames),
                [
                    'wagtail_editor',
                    'wagtail_admin',
                    'wagtail.flint.oursites.com-wagtail_editor_local',
                    'wagtail.flint.oursites.com-wagtail_admin_local',
                    'test_admin',
                    'superuser'
                ]
            )

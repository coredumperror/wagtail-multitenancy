from ads_extras.testing.dummy import Dummy
from django.contrib.auth.models import Group
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer

from ..views.groups import delete
from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin


class TestGroupDelete(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()
        cls.wagtail_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'wagtail.flint.oursites.com',
        })
        cls.test_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'test.flint.oursites.com',
        })

    def setUp(self):
        super(TestGroupDelete, self).setUp()

        # Logger dummy
        self.logger_dummy = Dummy(warning=Dummy(), info=Dummy())

        # When testing with permissions panels, we need to dummy out render() since the template can't handle being
        # given a fake set of permissions_panels.
        self.render_dummy = Dummy(default_return='rendered template')

        # Messages dummy.
        self.messages_dummy = Dummy(error=Dummy(), success=Dummy(), button=Dummy())

        # Dummy for the permissions_denied() function we use to lock non-superusers out of edits to other Sites' Groups.
        self.permission_denied_dummy = Dummy(default_return='Permissions Denied!')

    ############
    # TESTS
    ############

    def test_delete_group_view_routing(self):
        self.login('superuser')
        # First, test to make sure the routing works.
        response = self.client.get(
            reverse('wagtailusers_groups:delete', args=[self.test_admins_group.pk]),
            HTTP_HOST=self.wagtail_site.hostname
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailusers/groups/confirm_delete.html')

    def test_delete_group_view_permissions(self):
        # Confirm that unpriviledged users can't access the view.
        self.login('wagtail_editor')
        response = self.client.get(
            reverse('wagtailusers_groups:delete', args=[self.test_admins_group.pk]),
            HTTP_HOST=self.wagtail_site.hostname
        )
        self.assert_permission_denied_redirect(response)

    def test_delete_group_view_other_site_admins_cant_delete(self):
        with Replacer() as r:
            r.replace('wagtail_patches.views.groups.permission_denied', self.permission_denied_dummy)
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)

            # Confirm that priviledged non-superusers can't access the edit view for a Group belonging to another site.
            request = self.wagtail_factory.get('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            result = delete(request, self.test_admins_group.pk)
            self.assertEqual(len(self.permission_denied_dummy.calls), 1)
            self.assertEqual(result, self.permission_denied_dummy.default_return)

    def test_delete_group_view_happy_path_POST(self):
        with Replacer() as r:
            # We can't dummy out the form until we start testing the view function directly, because the render
            # pipeline will crash if the form is a dummy.
            r.replace('wagtail_patches.views.groups.TemplateResponse', self.render_dummy)
            r.replace('wagtail_patches.views.groups.permission_denied', self.permission_denied_dummy)
            r.replace('wagtail_patches.views.groups.messages', self.messages_dummy)

            self.login('wagtail_admin')
            response = self.client.post(
                reverse('wagtailusers_groups:delete', args=[self.wagtail_admins_group.pk]),
                HTTP_HOST=self.wagtail_site.hostname
            )

            self.assertEqual(len(self.messages_dummy.success.calls), 1)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailusers_groups:index'))

            # Confirm that the group is deleted.
            with self.assertRaises(Group.DoesNotExist):
                Group.objects.get(pk=self.wagtail_admins_group.pk)

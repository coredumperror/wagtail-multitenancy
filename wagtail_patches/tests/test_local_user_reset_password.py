from ads_extras.testing.dummy import Dummy
from django.conf import settings
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer, LogCapture
from wagtail_patches.forms import LocalUserAdminResetPasswordForm

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin
from ..views.users import admin_reset_password


class TestLocalUserResetPassword(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()
        cls.wagtail_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'wagtail.flint.oursites.com',
        })

    def setUp(self):
        super(TestLocalUserResetPassword, self).setUp()

        # Logger dummy.
        self.logger_dummy = Dummy(warning=Dummy(), info=Dummy())
        # Form dummy for view tests. self.form_dummy().is_valid() returns False by default.
        self.form_dummy = Dummy(
            default_return=Dummy(
                is_valid=Dummy(
                    default_return=False
                ),
                save=Dummy(
                    default_return=Dummy()
                )
            ),
        )
        # Messages dummy.
        self.messages_dummy = Dummy(error=Dummy(), success=Dummy(), button=Dummy())

    ############
    # TESTS
    ############

    def test_form_save(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        form_data = {'username': 'wagtail_editor', 'email': 'blah@blah.com'}
        # Create the form with valid POST data.
        form = LocalUserAdminResetPasswordForm(form_data)

        # Confirm that the given form data passes validation.
        self.assertTrue(form.is_valid())

        # Save the form, and confirm that it sends the email properly.
        mail_dummy = Dummy()
        with Replacer() as r:
            r.replace('wagtail_patches.forms.LocalUserAdminResetPasswordForm.send_mail', mail_dummy)
            with LogCapture() as capture:
                form.save(request)

        self.assertEqual(len(mail_dummy.calls), 1)
        self.assertEqual(mail_dummy.calls[0]['args'][2]['user'].username, form_data['username'])
        self.assertEqual(mail_dummy.calls[0]['args'][2]['domain'], request.site.hostname)
        self.assertEqual(mail_dummy.calls[0]['kwargs']['from_email'], settings.SERVER_EMAIL)
        self.assertTrue('user.local.password_reset.admin' in str(capture))

    def test_local_user_reset_password_view_GET(self):
        self.login('wagtail_admin')

        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LocalUserAdminResetPasswordForm', self.form_dummy)
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)

            # First, test to make sure the routing works.
            response = self.client.get(
                reverse('wagtailusers_users:admin_reset_password', args=[self.wagtail_editor.username]),
                HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'wagtail_patches/users/admin_reset_password.html')
            self.form_dummy.reset_dummy()

            # Confirm that unpriviledged users can't access the view.
            self.login('wagtail_editor')
            response = self.client.get(
                reverse('wagtailusers_users:admin_reset_password', args=[self.wagtail_editor.username]),
                HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))
            self.assertEqual(len(self.messages_dummy.error.calls), 1)

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.get('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = admin_reset_password(request, self.wagtail_editor.username)

            self.assertEqual(response.template_name, 'wagtail_patches/users/admin_reset_password.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(response.context_data['user'].pk, self.wagtail_editor.pk)
            self.assertEqual(len(self.form_dummy.calls), 1)

    def test_local_user_reset_password_view_POST_invalid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False.
            r.replace('wagtail_patches.views.users.LocalUserAdminResetPasswordForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            # First, test to make sure the routing works.
            form_data = {'username': 'wagtail_editor', 'email': 'blah@blah.com'}
            response = self.client.post(
                reverse('wagtailusers_users:admin_reset_password', args=[self.wagtail_editor.username]), data=form_data,
                HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'wagtail_patches/users/admin_reset_password.html')
            self.form_dummy.reset_dummy()
            self.messages_dummy.reset_dummy()

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.post(
                reverse('wagtailusers_users:admin_reset_password', args=[self.wagtail_editor.username]), data=form_data,
                HTTP_HOST=self.wagtail_site.hostname
            )
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = admin_reset_password(request, self.wagtail_editor.username)

            self.assertEqual(response.template_name, 'wagtail_patches/users/admin_reset_password.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(response.context_data['user'].pk, self.wagtail_editor.pk)
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request.POST)

    def test_edit_local_user_view_POST_valid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False, so we need to change that for the valid data test.
            self.form_dummy.default_return.is_valid = Dummy(default_return=True)
            r.replace('wagtail_patches.views.users.LocalUserAdminResetPasswordForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            form_data = {'username': 'wagtail_editor', 'email': 'blah@blah.com'}
            request = self.wagtail_factory.post(
                reverse('wagtailusers_users:admin_reset_password', args=[self.wagtail_editor.username]), data=form_data
            )
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = admin_reset_password(request, self.wagtail_editor.username)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailusers_users:index'))
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request.POST)

            # form.is_valid() returned true, so the user should have been saved and been informed about success.
            self.assertEqual(len(self.form_dummy.default_return.save.calls), 1)
            self.assertEqual(len(self.messages_dummy.success.calls), 1)
            self.assertEqual(self.messages_dummy.success.calls[0]['args'][0], request)

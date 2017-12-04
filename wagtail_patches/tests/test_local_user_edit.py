from ads_extras.testing.dummy import Dummy
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer, LogCapture
from wagtail_patches.forms import LocalUserEditForm

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin
from ..views.users import edit


class TestLocalUserEdit(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

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
        super(TestLocalUserEdit, self).setUp()

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

        # Dummies for forcing a password to be considered as usable or not.
        self.password_not_usable_dummy = Dummy(default_return=False)
        self.password_is_usable_dummy = Dummy(default_return=True)

    def safe_get_user(self, user):
        """
        This function exists due to a quirk in our test setup. Because we store a persistant instance of each
        of the Users created during test init (e.g. self.wagtail_editor), those instances don't get reset when the
        TransactionalTestCase rolls back the changes from the previous test.
        So, to avoid problems with inconsistent test data, we mustn't ever pass e.g. self.wagtail_editor directly into
        the edit form.
        """
        return get_user_model().objects.get(pk=user.pk)

    ############
    # TESTS
    ############

    def test_local_form_init(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        # Create the form and make the sure the initialization worked as exepected.
        form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_editor))
        self.assertEqual(form.request, request)
        # Non-superusers cannot change a User's is_superuser status.
        self.assertNotIn('is_superuser', form.fields)
        # Non-superusers only see the Groups' shortnames.
        self.assertEqual(
            form.fields['groups'].choices,
            [(self.wagtail_admins_group.pk, 'Admins'), (self.wagtail_editors_group.pk, 'Editors')]
        )
        self.assertTrue(form.fields['groups'].required)
        self.assertEqual(form.fields['groups'].error_messages['required'], form.error_messages['group_required'])
        self.assertIn('uncheck this box', form.fields['is_active'].help_text)

    def test_superusers_can_be_ungrouped(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        form_data = {
            'username': 'wagtail_user1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'groups': [],
            'is_superuser': True,
            'is_active': True,
        }

        form = LocalUserEditForm(request, self.superuser, form_data)

        # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
        with LogCapture():
            valid = form.is_valid()
        self.assertTrue(valid)
        # Comparing the empty form.cleaned_data['groups'] directly to the empty form_data['groups'] doesn't work,
        # I think because the cleaned data isn't an actualy list. Casting it to list() works, though.
        self.assertEqual(list(form.cleaned_data['groups']), form_data['groups'])

    def test_superuser_can_assign_local_user_to_group_andor_set_user_as_superuser_but_not_neither(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        form_data = {
            'username': 'wagtail_user1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'groups': [],
            'is_superuser': True,
            'is_active': True,
        }

        with LogCapture():
            form_data.update({'is_superuser': True, 'groups': [], 'is_active': True})
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_admin), form_data)
            valid = form.is_valid()
            self.assertTrue(valid)

            form_data.update({'is_superuser': True, 'groups': [self.wagtail_editors_group.pk], 'is_active': True})
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_admin), form_data)
            valid = form.is_valid()
            self.assertTrue(valid)

            form_data.update({'is_superuser': False, 'groups': [self.wagtail_editors_group.pk], 'is_active': True})
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_admin), form_data)
            valid = form.is_valid()
            self.assertTrue(valid)

            form_data.update({'is_superuser': False, 'groups': [], 'is_active': True})
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_admin), form_data)
            valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(form.errors['groups'][0], form.error_messages['group_required_superuser'])

    def test_assign_local_user_to_another_sites_groups_is_disallowed(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        form_data = {
            'username': 'wagtail_user1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'groups': [self.test_editors_group.pk],
            'is_active': True,
        }

        with LogCapture():
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_editor), form_data)
            valid = form.is_valid()
            self.assertFalse(valid)
            self.assertIn('Select a valid choice', form.errors['groups'][0])

    def test_edit_local_user_successfully(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        form_data = {
            'username': 'wagtail_user1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'groups': [self.wagtail_admins_group.pk, self.wagtail_editors_group.pk],
            'is_active': True,
        }

        with LogCapture() as capture:
            self.assertSequenceEqual(self.wagtail_editor.groups.all(), [self.wagtail_editors_group])
            form = LocalUserEditForm(request, self.safe_get_user(self.wagtail_editor), form_data)
            valid = form.is_valid()
            self.assertTrue(valid)
            user = form.save()
            # Confirm that the user's personal info now matches the form_data.
            self.assertEqual(user.username, request.site.hostname + '-' + form_data['username'])
            self.assertEqual(user.email, form_data['email'])
            self.assertEqual(user.first_name, form_data['first_name'])
            self.assertEqual(user.last_name, form_data['last_name'])
            self.assertSequenceEqual(user.groups.all(), [self.wagtail_admins_group, self.wagtail_editors_group])
            self.assertIn("user.local.update", str(capture))
            self.assertIn("'username'", str(capture))
            self.assertIn("'email'", str(capture))
            self.assertIn("'first_name'", str(capture))
            self.assertIn("'last_name'", str(capture))

    def test_edit_local_user_view_GET(self):
        self.login('wagtail_admin')

        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LocalUserEditForm', self.form_dummy)
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)
            # Need to force the passwords to be considered usable so that form code thinks the User is a Local user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_is_usable_dummy)

            # First, test to make sure the routing works.
            response = self.client.get(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'wagtail_patches/users/edit.html')
            self.form_dummy.reset_dummy()

            # Confirm that unpriviledged users can't access the view.
            self.login('wagtail_editor')
            response = self.client.get(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))
            self.assertEqual(len(self.messages_dummy.error.calls), 1)

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.get('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = edit(request, self.wagtail_editor.pk)

            self.assertEqual(response.template_name, 'wagtail_patches/users/edit.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(response.context_data['user'].pk, self.wagtail_editor.pk)
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy.calls[0]['args'][1].pk, self.wagtail_editor.pk)

            # Confirm that a non-superusers can't edit a superuser.
            response = edit(request, self.superuser.pk)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))

            # Confirm that a non-superusers can't edit a user belonging to another Site.
            response = edit(request, self.test_admin.pk)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))

    def test_edit_local_user_view_POST_invalid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False.
            r.replace('wagtail_patches.views.users.LocalUserEditForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)
            # Need to force the passwords to be considered usable so that form code thinks the User is a Local user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_is_usable_dummy)

            # First, test to make sure the routing works.
            form_data = {'groups': [self.test_editors_group.pk]}
            response = self.client.post(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), data=form_data,
                HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'wagtail_patches/users/edit.html')
            self.form_dummy.reset_dummy()
            self.messages_dummy.reset_dummy()

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.post(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), data=form_data
            )
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = edit(request, self.wagtail_editor.pk)

            self.assertEqual(response.template_name, 'wagtail_patches/users/edit.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(response.context_data['user'].pk, self.wagtail_editor.pk)
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy.calls[0]['args'][1].pk, self.wagtail_editor.pk)
            self.assertEqual(self.form_dummy.calls[0]['args'][2], request.POST)

            self.assertEqual(len(self.messages_dummy.success.calls), 0)
            self.assertEqual(len(self.messages_dummy.error.calls), 1)
            self.assertEqual(self.messages_dummy.error.calls[0]['args'][0], request)
            self.assertEqual(
                self.messages_dummy.error.calls[0]['args'][1], 'The user could not be saved due to errors.'
            )

    def test_edit_local_user_view_POST_valid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False, so we need to change that for the valid data test.
            self.form_dummy.default_return.is_valid = Dummy(default_return=True)
            r.replace('wagtail_patches.views.users.LocalUserEditForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)
            # Need to force the passwords to be considered usable so that form code thinks the User is a Local user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_is_usable_dummy)

            form_data = {'groups': [self.wagtail_admins_group.pk, self.wagtail_editors_group.pk]}
            request = self.wagtail_factory.post(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), data=form_data
            )
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = edit(request, self.wagtail_editor.pk)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailusers_users:index'))
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy.calls[0]['args'][1].pk, self.wagtail_editor.pk)
            self.assertEqual(self.form_dummy.calls[0]['args'][2], request.POST)

            # form.is_valid() returned true, so the user should have been saved and been informed about success.
            self.assertEqual(len(self.form_dummy.default_return.save.calls), 1)
            self.assertEqual(len(self.messages_dummy.success.calls), 1)
            self.assertEqual(self.messages_dummy.success.calls[0]['args'][0], request)

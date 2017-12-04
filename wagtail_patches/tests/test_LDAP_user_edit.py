import ldap
from ads_extras.testing.dummy import Dummy
from django.http.response import HttpResponseRedirect
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer, LogCapture
from with_asserts.mixin import AssertHTMLMixin
from wagtail_patches.forms import LDAPUserEditForm

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin, thrower
from core.tests.factories.user import UserFactory
from ..views.users import edit


class TestLDAPUserEdit(SecureClientMixin, TestCase, AssertHTMLMixin, MultitenantSiteTestingMixin):

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
        super(TestLDAPUserEdit, self).setUp()

        # Dummy for search_ldap_for_user(), returning good data.
        self.mock_email = 'blah@blah.com'
        self.mock_sn = 'Shmoe'
        self.mock_given_name = 'Joe'
        self.ldap_search_dummy = Dummy(
            default_return=('fake_dn', {
                'givenName': [self.mock_given_name],
                'sn': [self.mock_sn],
                'CAPPrimaryEmail': [self.mock_email],
            })
        )
        # Dummy for when search_ldap_for_user() should fail.
        self.ldap_search_dummy_error = lambda x: thrower(ldap.LDAPError('error!'))  # NOQA
        # Dummy for when search_ldap_for_user() should return no results.
        self.ldap_search_dummy_no_results = Dummy(default_return=None)
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

    ############
    # TESTS
    ############

    def test_LDAP_form_init_non_superuser(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        # Create the form and make the sure the initialization worked as exepected.
        form = LDAPUserEditForm(request, self.wagtail_editor)
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
        self.assertNotIn('is_active', form.fields)

    def test_LDAP_form_init_superuser(self):
        # Only superusers can see the is_active checkbox for LDAP users
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site

        # Create the form and make the sure the initialization worked as exepected.
        form = LDAPUserEditForm(request, self.wagtail_editor)
        self.assertIn('is_superuser', form.fields)
        self.assertIn('is_active', form.fields)

    def test_superusers_can_be_ungrouped(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)

            form_data = {'is_superuser': True, 'groups': [], 'is_active': True}
            form = LDAPUserEditForm(request, self.superuser, form_data)

            # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
            with LogCapture():
                valid = form.is_valid()
            self.assertTrue(valid)
            # Comparing the empty form.cleaned_data['groups'] directly to the empty form_data['groups'] doesn't work,
            # I think because the cleaned data isn't an actualy list. Casting it to list() works, though.
            self.assertEqual(list(form.cleaned_data['groups']), form_data['groups'])

    def test_superuser_can_assign_LDAP_user_to_group_andor_set_user_as_superuser_but_not_neither(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site

        with LogCapture():
            with Replacer() as r:
                r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)

                form_data = {'is_superuser': True, 'groups': [], 'is_active': True}
                form = LDAPUserEditForm(request, self.wagtail_admin, form_data)
                valid = form.is_valid()
                self.assertTrue(valid)

                form_data = {'is_superuser': True, 'groups': [self.wagtail_editors_group.pk], 'is_active': True}
                form = LDAPUserEditForm(request, self.wagtail_admin, form_data)
                valid = form.is_valid()
                self.assertTrue(valid)

                form_data = {'is_superuser': False, 'groups': [self.wagtail_editors_group.pk], 'is_active': True}
                form = LDAPUserEditForm(request, self.wagtail_admin, form_data)
                valid = form.is_valid()
                self.assertTrue(valid)

                form_data = {'is_superuser': False, 'groups': [], 'is_active': True}
                form = LDAPUserEditForm(request, self.wagtail_admin, form_data)
                valid = form.is_valid()
                self.assertFalse(valid)
            self.assertEqual(form.errors['groups'][0], form.error_messages['group_required_superuser'])

    def test_assign_LDAP_user_to_another_sites_groups_is_disallowed(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)

            form_data = {'groups': [self.test_editors_group.pk]}
            form = LDAPUserEditForm(request, self.wagtail_editor, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertIn('Select a valid choice', form.errors['groups'][0])

    def test_edit_LDAP_user_with_LDAP_error_during_save(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy_error)

            form_data = {'groups': [self.wagtail_admins_group.pk]}
            form = LDAPUserEditForm(request, self.wagtail_editor, form_data)
            valid = form.is_valid()
            self.assertTrue(valid)
            # We use commit=False to make sure that self.wagtail_editor hasn't changed.
            with LogCapture() as capture:
                user = form.save(commit=False)
            # Confirm that the user's personal info hasn't changed.
            self.assertEqual(user.email, self.wagtail_editor.email)
            self.assertEqual(user.first_name, self.wagtail_editor.first_name)
            self.assertEqual(user.last_name, self.wagtail_editor.last_name)
            # ldap lookup fails because the mock is configured to fail
            self.assertTrue('user.update_from_ldap.failed' in str(capture))

    def test_edit_LDAP_user_successfully(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            self.assertSequenceEqual(self.wagtail_editor.groups.all(), [self.wagtail_editors_group])
            form_data = {'groups': [self.wagtail_admins_group.pk, self.wagtail_editors_group.pk]}
            form = LDAPUserEditForm(request, self.wagtail_editor, form_data)
            valid = form.is_valid()
            self.assertTrue(valid)
            with LogCapture() as capture:
                user = form.save()

            # Confirm that the user's personal info hasn't changed.
            self.assertEqual(user.email, self.mock_email)
            self.assertEqual(user.first_name, self.mock_given_name)
            self.assertEqual(user.last_name, self.mock_sn)
            self.assertSequenceEqual(user.groups.all(), [self.wagtail_admins_group, self.wagtail_editors_group])

            # log messages
            self.assertTrue('user.update_from_ldap.success' in str(capture))
            # groups should have been updated for our user
            self.assertTrue('<Group: wagtail.flint.oursites.com Admins>' in str(capture))

    def test_edit_LDAP_user_view_GET(self):
        self.login('wagtail_admin')
        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LDAPUserEditForm', self.form_dummy)
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)
            # Need to force the passwords to be considered unusable so that form code thinks the User is an LDAP user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_not_usable_dummy)

            # First, test to make sure the routing works.
            response = self.client.get(
                reverse('wagtailusers_users:edit', args=[self.wagtail_editor.pk]), HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'wagtail_patches/users/edit.html')
            self.form_dummy.reset_dummy()

            # Confirm that unprivileged users can't access the view.
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

    def test_edit_LDAP_user_view_POST_invalid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False.
            r.replace('wagtail_patches.views.users.LDAPUserEditForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)
            # Need to force the passwords to be considered unusable so that form code thinks the User is an LDAP user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_not_usable_dummy)

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

    def test_edit_LDAP_user_view_POST_valid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False, so we need to change that for the valid data test.
            self.form_dummy.default_return.is_valid = Dummy(default_return=True)
            r.replace('wagtail_patches.views.users.LDAPUserEditForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)
            # Need to force the passwords to be considered unusable so that form code thinks the User is an LDAP user.
            r.replace('django.contrib.auth.base_user.is_password_usable', self.password_not_usable_dummy)

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

    def test_admin_user_sees_remove_user_button(self):
        ldap_user = UserFactory(
            username='ldap_user',
            first_name='LDAP',
            last_name='User',
            groups=[self.wagtail_editors_group]
        )
        ldap_user.set_unusable_password()
        ldap_user.save()
        self.login('wagtail_admin')
        response = self.client.get(
            reverse('wagtailusers_users:edit', args=[ldap_user.pk]),
            HTTP_HOST="wagtail.flint.oursites.com"
        )
        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'div.name') as (name, ):
            self.assertTrue(name.text_content().endswith('LDAP User'))
        with self.assertHTML(response.content, 'ul.button-bar li.right a') as (button, ):
            self.assertEqual(button.text.strip(), "Remove User From This Site")
        self.assertNotHTML(response.content, 'input[name="is_active"]')

    def test_superuser_sees_active_checkbox(self):
        ldap_user = UserFactory(
            username='ldap_user',
            first_name='LDAP',
            last_name='User',
            groups=[self.wagtail_editors_group]
        )
        ldap_user.set_unusable_password()
        ldap_user.save()
        self.login('superuser')
        response = self.client.get(
            reverse('wagtailusers_users:edit', args=[ldap_user.pk]), HTTP_HOST=self.wagtail_site.hostname
        )
        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'div.name') as (name, ):
            self.assertTrue(name.text_content().endswith('LDAP User'))
        with self.assertHTML(response.content, 'input[name="is_active"]') as checkbox:
            self.assertEqual(len(checkbox), 1)
        self.assertNotHTML(response.content, 'ul.button-bar li.right a')

    def test_admin_remove_user_button_removes_user(self):
        ldap_user = UserFactory(
            username='ldap_user',
            first_name='LDAP',
            last_name='User',
            groups=[self.wagtail_editors_group]
        )
        ldap_user.set_unusable_password()
        ldap_user.save()

        # confirm the user is in the wagtail_editors group
        self.assertTrue(self.wagtail_editors_group.user_set.filter(pk=ldap_user.pk).exists())

        self.login('wagtail_admin')
        response = self.client.get(
            reverse('wagtailusers_users:edit', args=[ldap_user.pk]), HTTP_HOST=self.wagtail_site.hostname
        )
        self.assertEqual(response.status_code, 200)
        with self.assertHTML(response.content, 'ul.button-bar li.right a') as (button, ):
            response = self.client.get(button.attrib['href'], HTTP_HOST=self.wagtail_site.hostname)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, reverse('wagtailusers_users:index'))

        # confirm the user is no longer in the wagtail_editors group
        self.assertFalse(self.wagtail_editors_group.user_set.filter(pk=ldap_user.pk).exists())

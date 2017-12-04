import re
from ads_extras.testing.dummy import Dummy
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer, LogCapture
from wagtail_patches.forms import LocalUserCreateForm

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin
from core.tests.factories.user import DEFAULT_PASSWORD
from core.utils import user_is_member_of_site

from ..views.users import create_local


class TestLocalUserCreate(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

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
        super(TestLocalUserCreate, self).setUp()

        # Logger dummy
        self.logger_dummy = Dummy(warning=Dummy(), info=Dummy(), bind=Dummy())
        # Form dummy, for view tests
        self.form_dummy_invalid = Dummy(
            default_return=Dummy(
                is_valid=Dummy(
                    default_return=False
                ),
                save=Dummy(
                    default_return=Dummy()
                )
            ),
        )
        self.form_dummy_valid = Dummy(
            default_return=Dummy(
                is_valid=Dummy(
                    default_return=True
                ),
                save=Dummy(
                    default_return=Dummy()
                )
            ),
        )
        # Messages dummy
        self.messages_dummy = Dummy(error=Dummy(), success=Dummy(), button=Dummy())

    ############
    # TESTS
    ############

    def test_create_brand_new_local_nonsuperuser_happy_path(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        # Should create a new user named "wagtail_user1" in the "wagtail.flint.oursites.com Admins" Group.
        form_data = {
            'username': 'wagtail_user1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
            'groups': [self.wagtail_admins_group.pk],
        }

        # Confirm that this user doesn't already exist, so we know this is the "brand new user" workflow.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        # Create the form and make the sure the initialization worked as exepected.
        form = LocalUserCreateForm(request, form_data)
        # Non-superusers cannot set a new user as a superuser.
        self.assertNotIn('is_superuser', form.fields)
        # Non-superusers only see the Groups' shortnames.
        self.assertEqual(
            form.fields['groups'].choices,
            [(self.wagtail_admins_group.pk, 'Admins'), (self.wagtail_editors_group.pk, 'Editors')]
        )
        self.assertTrue(form.fields['groups'].required)
        self.assertEqual(form.fields['groups'].error_messages['required'], form.error_messages['group_required'])

        # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
        valid = form.is_valid()
        self.assertTrue(valid)

        with LogCapture() as capture:
            new_user = form.save()

        # the username in the database should automatically be prefixed with the
        # current site hostname
        self.assertEqual(new_user.username, request.site.hostname + "-" + form_data['username'])
        self.assertEqual(new_user.email, form_data['email'])
        self.assertEqual(new_user.first_name, form_data['first_name'])
        self.assertEqual(new_user.last_name, form_data['last_name'])
        self.assertTrue(new_user.check_password(form_data['password1']))
        self.assertTrue(user_is_member_of_site(new_user, request.site))
        self.assertEqual(list(new_user.groups.all()), [self.wagtail_admins_group])

        self.assertIn('user.local.create', str(capture))

    def test_create_brand_new_local_superuser_happy_path(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        # Should create a new user named "superuser1" who is a superuser.
        form_data = {
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
            'is_superuser': True,
            'username': 'wagtail_user1',
        }

        # Confirm that this user doesn't already exist.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        # Create the form and make the sure the initialization worked as exepected.
        form = LocalUserCreateForm(request, form_data)
        # Superusers CAN set a new user as a superuser.
        self.assertIn('is_superuser', form.fields)
        # Superusers see all Groups' full names.
        self.assertSequenceEqual(
            # Need to convert to a list here, since it's currently a ModelChoiceIterator.
            list(form.fields['groups'].choices),
            [(g.pk, g.name) for g in Group.objects.all()]
        )
        self.assertFalse(form.fields['groups'].required)

        # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
        valid = form.is_valid()
        self.assertTrue(valid)

        with LogCapture() as capture:
            new_user = form.save()

        # local superusers' usernames in the database should NOT be prefixed
        # with the local site name
        self.assertEqual(new_user.username, form_data['username'])
        self.assertTrue(new_user.is_superuser)
        self.assertEqual(new_user.email, form_data['email'])
        self.assertEqual(new_user.first_name, form_data['first_name'])
        self.assertEqual(new_user.last_name, form_data['last_name'])
        self.assertTrue(new_user.check_password(form_data['password1']))
        self.assertFalse(user_is_member_of_site(new_user, request.site))

        # Make sure we logged it correctly.
        self.assertIn('user.local.create', str(capture))
        self.assertIsNotNone(re.search("'groups': '.*Superusers", str(capture)))

    def test_superuser_has_to_assign_local_user_to_group_or_set_superuser(self):
        request = self.wagtail_factory.get('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        # Should fail to create a user since no group or superuser flag is set.
        form_data = {
            'username': 'superuser1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
        }

        # Confirm that this user doesn't already exist.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        # Form_data doesn't set a Group or the is_superuser flag, so the form should throw an error.
        form = LocalUserCreateForm(request, form_data)
        with LogCapture():
            valid = form.is_valid()
        self.assertFalse(valid)
        self.assertEqual(len(form.errors), 1)
        self.assertIn('groups', form.errors)
        self.assertEqual(
            form.errors['groups'][0],
            LocalUserCreateForm.error_messages['group_required_superuser']
        )

    def test_local_nonsuperuser_cannot_create_new_superuser(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        # Would create a new user named "superuser1" who is a superuser, if that were allowed.
        form_data = {
            'username': 'superuser1',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
            'is_superuser': True,
            'groups': [self.wagtail_admins_group.pk],
        }

        # Confirm that this user doesn't already exist.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        form = LocalUserCreateForm(request, form_data)

        # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
        valid = form.is_valid()
        self.assertTrue(valid)
        # There should be no "is_superuser" entry in cleaned_data, because the is_superuser form field is excluded.
        self.assertNotIn('is_superuser', form.cleaned_data)

        # The resulting User should not be a superuser.
        with LogCapture() as capture:
            new_user = form.save()
        self.assertFalse(new_user.is_superuser)

        # Make sure we logged it correctly.
        self.assertIn('user.local.create', str(capture))
        self.assertIsNone(re.search("'groups': '.*Superusers", str(capture)))

    def test_local_duplicate_username_error(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        form_data = {
            # A User named wagtail_editor already exists.
            'username': 'wagtail_editor_local',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
            'groups': [self.wagtail_editors_group.pk],
        }

        # We expect the form to throw a dulicate_username error since you can't
        # create a local User with a username that's already in use.  We created
        # our local wagtail_editor_local already in setUpTestData().
        form = LocalUserCreateForm(request, form_data)
        with LogCapture():
            valid = form.is_valid()
        self.assertFalse(valid)
        self.assertEqual(len(form.errors), 1)
        self.assertIn('username', form.errors)

    def test_create_local_user_belonging_to_other_site_groups_is_disallowed(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        form_data = {
            'username': 'test_user',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': DEFAULT_PASSWORD,
            'groups': [self.test_editors_group.pk],
        }

        # Create and validate the form. We expect the form to throw an Invalid
        # Choice error, since Groups that aren't connected to the current Site
        # aren't in the choices list.
        form = LocalUserCreateForm(request, form_data)
        with LogCapture():
            valid = form.is_valid()
        self.assertFalse(valid)
        self.assertEqual(len(form.errors), 1)
        self.assertIn('groups', form.errors)
        self.assertIn('Select a valid choice', form.errors['groups'][0])

    def test_create_local_user_password_confirmation_field(self):
        request = self.wagtail_factory.get('/')
        request.user = self.wagtail_admin
        request.site = self.wagtail_site
        form_data = {
            'username': 'test_user',
            'email': 'wagtail@email.com',
            'first_name': 'John',
            'last_name': 'Wagtail',
            'password1': DEFAULT_PASSWORD,
            'password2': 'blah',
            'groups': [self.wagtail_editors_group.pk],
        }

        # Create and validate the form. We expect the form to throw an Invalid
        # Choice error, since Groups that aren't connected to the current Site
        # aren't in the choices list.
        form = LocalUserCreateForm(request, form_data)
        with LogCapture():
            valid = form.is_valid()
        self.assertFalse(valid)
        self.assertEqual(len(form.errors), 1)
        self.assertIn('password2', form.errors)
        self.assertEqual(form.error_messages['password_mismatch'], form.errors['password2'][0])

    def test_create_local_user_view_GET(self):
        self.login('superuser')

        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LocalUserCreateForm', self.form_dummy_valid)
            # Unlike most replacements, we can replace the module's origin here because it gets imported at runtime,
            # rather than being imported at load time.
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)

            # First, test to make sure the routing works.
            response = self.client.get(reverse('wagtailusers_users:add_local'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.template_name, 'wagtail_patches/users/create_local.html')
            self.form_dummy_valid.reset_dummy()

            # Confirm that unpriviledged users can't access the view.
            self.login('wagtail_editor')
            response = self.client.get(reverse('wagtailusers_users:add_local'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))
            self.assertEqual(len(self.messages_dummy.error.calls), 1)

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.get('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = create_local(request)

            self.assertEqual(response.template_name, 'wagtail_patches/users/create_local.html')
            self.assertEqual(response.context_data['form'], self.form_dummy_valid.default_return)
            self.assertEqual(len(self.form_dummy_valid.calls), 1)
            self.assertEqual(self.form_dummy_valid.calls[0]['args'][0], request)

    def test_create_local_user_view_POST_invalid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, form_dummy.is_valid() returns False.
            r.replace('wagtail_patches.views.users.LocalUserCreateForm', self.form_dummy_invalid)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            # We're forcing is_vald to return False, so it doesn't matter what this data actually is.
            form_data = {
                'username': 'test_admin'
            }
            # First, test to make sure the routing works.
            response = self.client.post(
                reverse('wagtailusers_users:add_local'), data=form_data, HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.template_name, 'wagtail_patches/users/create_local.html')
            self.form_dummy_invalid.reset_dummy()
            self.messages_dummy.reset_dummy()

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.post(reverse('wagtailusers_users:add_local'), form_data)
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = create_local(request)

            self.assertEqual(response.template_name, 'wagtail_patches/users/create_local.html')
            self.assertEqual(response.context_data['form'], self.form_dummy_invalid.default_return)
            self.assertEqual(len(self.form_dummy_invalid.calls), 1)
            self.assertEqual(self.form_dummy_invalid.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy_invalid.calls[0]['args'][1], request.POST)

            self.assertEqual(len(self.messages_dummy.success.calls), 0)
            self.assertEqual(len(self.messages_dummy.error.calls), 1)
            self.assertEqual(self.messages_dummy.error.calls[0]['args'][0], request)
            self.assertEqual(
                self.messages_dummy.error.calls[0]['args'][1], 'The user could not be created due to errors.'
            )

    def test_create_local_user_view_POST_valid_data(self):
        self.login('superuser')

        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LocalUserCreateForm', self.form_dummy_valid)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            # We're forcing is_vald to return True, so it doesn't matter what this data actually is.
            form_data = {'username': 'test_admin', 'groups': [self.wagtail_editors_group.pk]}
            request = self.wagtail_factory.post(reverse('wagtailusers_users:add_local'), form_data)
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            response = create_local(request)

            self.assertEqual(response.url, reverse('wagtailusers_users:index'))
            self.assertEqual(len(self.form_dummy_valid.calls), 1)
            self.assertEqual(self.form_dummy_valid.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy_valid.calls[0]['args'][1], request.POST)

            # form.is_valid() returned true, so the user should have been saved, had their password garbled, and been
            # informed about success.
            self.assertEqual(len(self.form_dummy_valid.default_return.save.calls), 1)
            self.assertEqual(len(self.messages_dummy.success.calls), 1)
            self.assertEqual(self.messages_dummy.success.calls[0]['args'][0], request)

# TODO: Test the password confirmation field

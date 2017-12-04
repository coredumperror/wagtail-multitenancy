import ldap
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer, LogCapture
from wagtail.wagtailcore.models import Site
from wagtail_patches.forms import LDAPUserCreateForm

from ads_extras.testing.dummy import Dummy
from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin, thrower
from core.utils import user_is_member_of_site

from ..views.users import create


class TestLDAPUserCreate(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

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
        super(TestLDAPUserCreate, self).setUp()

        # Dummies out search_ldap_for_user(), returning good data.
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
        # Form dummy, for view tests
        self.form_dummy = Dummy(
            default_return=Dummy(
                is_valid=Dummy(
                    default_return=False
                ),
                save=Dummy(
                    default_return=Dummy(
                        set_unusable_password=Dummy()
                    )
                )
            ),
        )
        # Messages dummy
        self.messages_dummy = Dummy(error=Dummy(), success=Dummy(), button=Dummy())

    ############
    # TESTS
    ############

    def test_create_brand_new_LDAP_nonsuperuser_happy_path(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        # Should create a new user named "wagtail_user1" in the "wagtail.flint.oursites.com Admins" Group.
        form_data = {'username': 'wagtail_user1', 'groups': [self.wagtail_admins_group.pk]}

        # Confirm that this user doesn't already exist, so we know this is the "brand new user" workflow.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Create the form and make the sure the initialization worked as exepected.
            form = LDAPUserCreateForm(request, form_data)
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
            self.assertEqual(len(self.ldap_search_dummy.calls), 1)

            # Save the user to the database, which would populate it from LDAP, if it weren't being mocked to fail.
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy_error)
            with LogCapture() as capture:
                new_user = form.save()
            # ldap lookup fails because the mock is configured to fail
            self.assertTrue('user.update_from_ldap.failed' in str(capture))
            # Ensure we still created the user
            self.assertTrue('user.ldap.create' in str(capture))

            self.assertEqual(new_user.username, form_data['username'])
            # LDAP is mocked to error out. The population of these should have gracefully failed, leaving them unset.
            self.assertEqual(new_user.email, '')
            self.assertEqual(new_user.first_name, '')
            self.assertEqual(new_user.last_name, '')
            self.assertTrue(user_is_member_of_site(new_user, request.site))
            self.assertEqual(list(new_user.groups.all()), [self.wagtail_admins_group])

    def test_create_brand_new_LDAP_superuser_happy_path(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='superuser')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        # Should create a new user named "superuser1" who is a superuser.
        form_data = {'username': 'superuser1', 'is_superuser': True}

        # Confirm that this user doesn't already exist, so we know this is the "brand new user" workflow.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Create the form and make the sure the initialization worked as exepected.
            form = LDAPUserCreateForm(request, form_data)
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
            self.assertEqual(len(self.ldap_search_dummy.calls), 1)

            # Save the user to the database, which would populate it from LDAP, if it weren't being mocked out.
            with LogCapture() as capture:
                new_user = form.save()
            self.assertEqual(len(self.ldap_search_dummy.calls), 2)
            # ldap lookup
            self.assertTrue('user.update_from_ldap.success' in str(capture))
            # user creation
            self.assertTrue('user.ldap.create' in str(capture))

            self.assertEqual(new_user.username, form_data['username'])
            self.assertTrue(new_user.is_superuser)
            self.assertEqual(new_user.email, self.mock_email)
            self.assertEqual(new_user.first_name, self.mock_given_name)
            self.assertEqual(new_user.last_name, self.mock_sn)
            self.assertFalse(user_is_member_of_site(new_user, request.site))

    def test_superuser_has_to_assign_LDAP_user_to_group_or_set_superuser(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='superuser')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        # Should fail to create a user since no group or superuser flag is set.
        form_data = {'username': 'superuser1'}

        # Confirm that this user doesn't already exist, so we know this is the "brand new user" workflow.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Form_data doesn't set a Group or the is_superuser flag, so the form should throw an error.
            form = LDAPUserCreateForm(request, form_data)
            valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('groups', form.errors)
            self.assertEqual(
                form.errors['groups'][0],
                LDAPUserCreateForm.error_messages['group_required_superuser']
            )

    def test_LDAP_nonsuperuser_cannot_create_new_LDAP_superuser(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        # Should create a new user named "superuser1" who is a superuser.
        form_data = {'username': 'superuser1', 'is_superuser': True, 'groups': [self.wagtail_admins_group.pk]}

        # Confirm that this user doesn't already exist, so we know this is the "brand new user" workflow.
        self.assertFalse(get_user_model().objects.filter(username=form_data['username']).exists())

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            form = LDAPUserCreateForm(request, form_data)

            # Validate the form. We save the results to a variable due to a quirk in PyDev's debugger regarding forms.
            valid = form.is_valid()
            self.assertTrue(valid)
            # There should be no "is_superuser" entry in cleaned_data, because the is_superuser form field is excluded.
            self.assertNotIn('is_superuser', form.cleaned_data)

            # The resulting User should not be a superuser.
            with LogCapture() as capture:
                new_user = form.save()
            self.assertFalse(new_user.is_superuser)
            # ldap lookup
            self.assertTrue('user.update_from_ldap.success' in str(capture))
            # user creation
            self.assertTrue('user.ldap.create' in str(capture))
            self.assertTrue('Superusers' not in str(capture))

    def test_LDAP_duplicate_username_error(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        form_data = {'username': 'wagtail_editor', 'groups': [self.wagtail_editors_group.pk]}

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Create and validate the form. We expect the form to throw a dulicate_username error since you can't
            # create a user that's already a member of the current site. Which "wagtail_editor" is.
            form = LDAPUserCreateForm(request, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('username', form.errors)

            # Create and validate the form. We expect the form to throw a dulicate_username error since we don't let
            # the create user workflow mess with existing superusers.
            form_data['username'] = 'superuser'
            form = LDAPUserCreateForm(request, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('username', form.errors)

    def test_create_LDAP_user_belonging_to_other_site_groups_is_disallowed(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        form_data = {'username': 'test_user', 'groups': [self.test_editors_group.pk]}

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Create and validate the form. We expect the form to throw an Invalid Choice error, since Groups that
            # aren't connected to the current Site aren't in the choices list.
            form = LDAPUserCreateForm(request, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('groups', form.errors)
            self.assertIn('Select a valid choice', form.errors['groups'][0])

    def test_create_LDAP_user_with_username_that_is_not_in_LDAP(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        form_data = {'username': 'wagtail_user', 'groups': [self.wagtail_editors_group.pk]}

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy_no_results)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # We expect the form to throw an error about the user not existing in LDAP, because we've mocked the
            # search_ldap_for_user to return no results.
            form = LDAPUserCreateForm(request, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('username', form.errors)
            self.assertEqual(form.errors['username'][0], LDAPUserCreateForm.error_messages['not_in_ldap'])

    def test_create_LDAP_user_with_LDAP_error(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        form_data = {'username': 'wagtail_user', 'groups': [self.wagtail_editors_group.pk]}

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy_error)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # We expect the form to throw an error about the LDAP lookup failing, because we've mocked the
            # search_ldap_for_user to throw an exception.
            form = LDAPUserCreateForm(request, form_data)
            with LogCapture():
                valid = form.is_valid()
            self.assertFalse(valid)
            self.assertEqual(len(form.errors), 1)
            self.assertIn('username', form.errors)
            self.assertEqual(form.errors['username'][0], LDAPUserCreateForm.error_messages['ldap_lookup_failed'])

    def test_create_LDAP_user_which_already_exists(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        test_site = Site.objects.get(hostname='test.flint.oursites.com')
        # Should add wagtail editors group to test_admin, since test_admin already exists on the "test" site.
        form_data = {'username': 'test_admin', 'groups': [self.wagtail_editors_group.pk]}

        existing_user = get_user_model().objects.get(username=form_data['username'])
        # test_admin starts in both of the test site's Groups.
        self.assertEqual(len(existing_user.groups.all()), 2)
        self.assertTrue(user_is_member_of_site(existing_user, test_site))
        self.assertFalse(user_is_member_of_site(existing_user, request.site))

        with Replacer() as r:
            r.replace('wagtail_patches.forms.search_ldap_for_user', self.ldap_search_dummy)
            r.replace('core.utils.search_ldap_for_user', self.ldap_search_dummy)

            # Create and validate the form, then save. We expect everything to work, and for "test_editor" to now be in
            # two Groups.
            form = LDAPUserCreateForm(request, form_data)
            valid = form.is_valid()
            self.assertTrue(valid)

            # The resulting User should be the same user as we started with, but with another Group membership.
            with LogCapture() as capture:
                new_user = form.save()
            self.assertEqual(len(new_user.groups.all()), 3)
            self.assertTrue(user_is_member_of_site(new_user, test_site))
            self.assertTrue(user_is_member_of_site(new_user, request.site))

            # ldap lookup log message
            self.assertTrue('user.update_from_ldap.success' in str(capture))
            # user creation log message
            self.assertTrue('user.ldap.update' in str(capture))

    def test_create_LDAP_user_view_GET(self):
        self.login('superuser')

        with Replacer() as r:
            r.replace('wagtail_patches.views.users.LDAPUserCreateForm', self.form_dummy)
            # Unlike most replacements, we can replace the module's origin here because it gets imported at runtime,
            # rather than being imported at load time.
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)

            # First, test to make sure the routing works.
            response = self.client.get(reverse('wagtailusers_users:add'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.template_name, 'wagtail_patches/users/create.html')
            self.form_dummy.reset_dummy()

            # Confirm that unpriviledged users can't access the view.
            self.login('wagtail_editor')
            response = self.client.get(reverse('wagtailusers_users:add'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))
            self.assertEqual(len(self.messages_dummy.error.calls), 1)

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.get('/')
            request.user = get_user_model().objects.get(username='wagtail_admin')
            request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
            response = create(request)

            self.assertEqual(response.template_name, 'wagtail_patches/users/create.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)

    def test_create_LDAP_user_view_POST_invalid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False.
            r.replace('wagtail_patches.views.users.LDAPUserCreateForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            # First, test to make sure the routing works.
            form_data = {'username': 'test_admin', 'groups': [self.wagtail_editors_group.pk]}
            response = self.client.post(
                reverse('wagtailusers_users:add'), data=form_data, HTTP_HOST=self.wagtail_site.hostname
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.template_name, 'wagtail_patches/users/create.html')
            self.form_dummy.reset_dummy()
            self.messages_dummy.reset_dummy()

            # Now, the real unit test requires us to call the view function directly, since it's not
            # consistently possible to retrieve the request object from the output of the http testing client.
            request = self.wagtail_factory.post(reverse('wagtailusers_users:add'), form_data)
            request.user = get_user_model().objects.get(username='wagtail_admin')
            request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
            response = create(request)

            self.assertEqual(response.template_name, 'wagtail_patches/users/create.html')
            self.assertEqual(response.context_data['form'], self.form_dummy.default_return)
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy.calls[0]['args'][1], request.POST)

            self.assertEqual(len(self.messages_dummy.success.calls), 0)
            self.assertEqual(len(self.messages_dummy.error.calls), 1)
            self.assertEqual(self.messages_dummy.error.calls[0]['args'][0], request)
            self.assertEqual(
                self.messages_dummy.error.calls[0]['args'][1], 'The user could not be created due to errors.'
            )

    def test_create_LDAP_user_view_POST_valid_data(self):
        self.login('superuser')

        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False, so we need to change that for the valid data test.
            self.form_dummy.default_return.is_valid = Dummy(default_return=True)
            r.replace('wagtail_patches.views.users.LDAPUserCreateForm', self.form_dummy)
            r.replace('wagtail_patches.views.users.messages', self.messages_dummy)

            form_data = {'username': 'test_admin', 'groups': [self.wagtail_editors_group.pk]}
            request = self.wagtail_factory.post(reverse('wagtailusers_users:add'), form_data)
            request.user = get_user_model().objects.get(username='wagtail_admin')
            request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
            response = create(request)

            self.assertEqual(response.url, reverse('wagtailusers_users:index'))
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['args'][0], request)
            self.assertEqual(self.form_dummy.calls[0]['args'][1], request.POST)

            # form.is_valid() returned true, so the user should have been saved, had their password garbled, and been
            # informed about success.
            self.assertEqual(len(self.form_dummy.default_return.save.calls), 1)
            self.assertEqual(len(self.form_dummy.default_return.save.default_return.set_unusable_password.calls), 1)
            self.assertEqual(len(self.messages_dummy.success.calls), 1)
            self.assertEqual(self.messages_dummy.success.calls[0]['args'][0], request)

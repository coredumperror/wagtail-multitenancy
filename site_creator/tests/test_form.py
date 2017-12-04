from django.conf import settings
from django.test import TestCase
from django.contrib.auth.models import Group, Permission
from wagtail.tests.utils import WagtailTestUtils
from wagtail.wagtailcore.models import Site, Collection, GroupCollectionPermission, PAGE_PERMISSION_TYPES,\
    GroupPagePermission

from site_creator.forms import SiteCreationForm
from core.tests.factories.user import UserFactory
from core.utils import get_homepage_model
from core.utils import SiteSettings, get_installed_site_settings_class


class TestForm(TestCase, WagtailTestUtils):

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.form_data = {'hostname': 'blah', 'site_name': 'Blah Dot Com'}

    def _has_permission(self, group, app_label, codename):
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        return perm in group.permissions.all()

    def _assert_page_and_collection_permissions(self, site, group, name):
        """
        Editors and Admins should have the same GroupPagePermissions and GroupCollectionPermissions.
        """
        TESTABLE_PERMS = PAGE_PERMISSION_TYPES[0:2] + [PAGE_PERMISSION_TYPES[4]]
        for permission_type, short_label, long_label in TESTABLE_PERMS:  # @UnusedVariable
            try:
                GroupPagePermission.objects.get(group=group, page=site.root_page, permission_type=permission_type)
            except GroupPagePermission.DoesNotExist:
                self.fail(
                    "No {} permission found for the Site's {} on the Site's Pages.".format(permission_type, name)
                )

        add_image_perm = Permission.objects.get(content_type__app_label='wagtailimages', codename='add_image')
        change_image_perm = Permission.objects.get(content_type__app_label='wagtailimages', codename='change_image')
        add_doc_perm = Permission.objects.get(content_type__app_label='wagtaildocs', codename='add_document')
        change_doc_perm = Permission.objects.get(content_type__app_label='wagtaildocs', codename='change_document')
        collection = Collection.objects.get(name=site.hostname)
        try:
            GroupCollectionPermission.objects.get(group=group, collection=collection, permission=add_image_perm)
        except GroupCollectionPermission.DoesNotExist:
            self.fail("No Add Image permission found for the Site's {} on the Site's Collection.".format(name))
        try:
            GroupCollectionPermission.objects.get(group=group, collection=collection, permission=change_image_perm)
        except GroupCollectionPermission.DoesNotExist:
            self.fail("No Change Image permission found for the Site's {} on the Site's Collection.".format(name))
        try:
            GroupCollectionPermission.objects.get(group=group, collection=collection, permission=add_doc_perm)
        except GroupCollectionPermission.DoesNotExist:
            self.fail("No Add Dcuemnt permission found for the Site's {} on the Site's Collection.".format(name))
        try:
            GroupCollectionPermission.objects.get(group=group, collection=collection, permission=change_doc_perm)
        except GroupCollectionPermission.DoesNotExist:
            self.fail("No Change Document permission found for the Site's {} on the Site's Collection.".format(name))

    def test_Site_object_gets_created(self):
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())

        # The only Site that should exist at this point is the one wagtailcore creates in its migrations.
        sites = Site.objects.all()
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0].root_page.title, 'Welcome to your new Wagtail site!')

        site = form.save(self.user)
        self.assertEqual(site.hostname, 'blah.{}'.format(settings.SERVER_DOMAIN))
        self.assertEqual(site.site_name, 'Blah Dot Com')
        self.assertEqual(site.port, 80)
        self.assertFalse(site.is_default_site)
        self.assertEqual(Site.objects.count(), 2)

    def test_new_homepage_gets_attached_to_Site(self):
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())

        # There should be no homepages before the form is saved.
        self.assertEqual(get_homepage_model().objects.count(), 0)

        site = form.save(self.user)
        self.assertEqual(site.root_page.title, '{} Homepage'.format(self.form_data['site_name']))
        self.assertEqual(get_homepage_model().objects.count(), 1)

    def test_new_Collection_gets_added_for_Site(self):
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())

        # There should be only 1 Collection (the root Collection) before the form is saved.
        self.assertEqual(Collection.objects.count(), 1)

        site = form.save(self.user)
        # The Collection isn't tied to the Site through anything but its name, so the only way to check it it to get it
        # directly out of the DB.
        try:
            Collection.objects.get(name=site.hostname)
        except Collection.DoesNotExist:
            self.fail("No Collection found with name matching new Site's hostname.")
        self.assertEqual(Collection.objects.count(), 2)

    def test_new_SiteSettings_gets_added_for_Site(self):
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())

        site = form.save(self.user)
        self.assertTrue(isinstance(site.settings, SiteSettings))

    def test_new_Groups_get_added_for_Site(self):
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())

        # Wagtail adds 2 Groups by default.
        self.assertEqual(Group.objects.count(), 2)

        site = form.save(self.user)
        self.assertTrue(isinstance(site.settings, SiteSettings))

        Group.objects.get(name='{} Admins'.format(site.hostname))
        Group.objects.get(name='{} Editors'.format(site.hostname))
        self.assertEqual(Group.objects.count(), 4)

    def test_new_Admins_Group_gets_correct_permissions(self):
        settings_class = get_installed_site_settings_class()
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())
        site = form.save(self.user)

        admins = Group.objects.get(name='{} Admins'.format(site.hostname))
        self.assertTrue(self._has_permission(
            admins, settings_class._meta.app_label, 'change_{}'.format(settings_class._meta.model_name)
        ))
        self.assertTrue(self._has_permission(admins, 'wagtailredirects', 'add_redirect'))
        self.assertTrue(self._has_permission(admins, 'wagtailredirects', 'change_redirect'))
        self.assertTrue(self._has_permission(admins, 'wagtailredirects', 'delete_redirect'))
        self.assertTrue(self._has_permission(admins, 'auth', 'add_user'))
        self.assertTrue(self._has_permission(admins, 'auth', 'change_user'))
        self.assertTrue(self._has_permission(admins, 'auth', 'delete_user'))

        self._assert_page_and_collection_permissions(site, admins, 'Admins')

    def test_new_Editors_Group_gets_correct_permissions(self):
        settings_class = get_installed_site_settings_class()
        form = SiteCreationForm(self.form_data)
        self.assertTrue(form.is_valid())
        site = form.save(self.user)

        # Editors should have none of the normal Permissions that Admins have.
        editors = Group.objects.get(name='{} Editors'.format(site.hostname))
        self.assertFalse(self._has_permission(
            editors, settings_class._meta.app_label, 'change_{}'.format(settings_class._meta.model_name)
        ))
        self.assertTrue(self._has_permission(editors, 'wagtailredirects', 'add_redirect'))
        self.assertTrue(self._has_permission(editors, 'wagtailredirects', 'change_redirect'))
        self.assertTrue(self._has_permission(editors, 'wagtailredirects', 'delete_redirect'))
        self.assertFalse(self._has_permission(editors, 'auth', 'add_user'))
        self.assertFalse(self._has_permission(editors, 'auth', 'change_user'))
        self.assertFalse(self._has_permission(editors, 'auth', 'delete_user'))

        self._assert_page_and_collection_permissions(site, editors, 'Editors')

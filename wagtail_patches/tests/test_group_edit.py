import copy
from ads_extras.testing.dummy import Dummy
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from testfixtures import Replacer
from wagtail_patches.forms import MultitenantGroupForm
from wagtail_patches.views.groups import get_permission_panel_instances

from ..views.groups import edit
from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin


class TestGroupEdit(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

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
        super(TestGroupEdit, self).setUp()

        # Logger dummy
        self.logger_dummy = Dummy(warning=Dummy(), info=Dummy())
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

        # permission_panels dummy, also for view tests.
        self.perm_panel_dummy = Dummy(
            is_valid=Dummy(
                # Returns true by default because it's much easier to test failure through form_dummy.
                default_return=True
            ),
            save=Dummy()
        )
        # We want 4 references to the same object so we can confirm that self.perm_panel_dummy was used 4 times.
        self.permission_panels_dummy = Dummy(default_return=[self.perm_panel_dummy] * 4)

        # When testing with permissions panels, we need to dummy out render() since the template can't handle being
        # given a fake set of permissions_panels.
        self.render_dummy = Dummy(default_return='rendered template')

        # Messages dummy.
        self.messages_dummy = Dummy(error=Dummy(), success=Dummy(), button=Dummy())

        # Creates a new Group named 'wagtail.flint.oursites.com Garbles'.
        # 2016-07-16: The IDs of the permissions changed at some point, which is why I now load them by
        # machine name to get the correct ID.
        self.perm_map = {p.codename: p for p in Permission.objects.all()}
        self.happy_path_form_data = {
            'name': 'wagtail.flint.oursites.com Garbles',
            'permissions': [
                self.perm_map['change_settings'].pk,
                self.perm_map['change_group'].pk,
                self.perm_map['change_user'].pk,
                self.perm_map['access_admin'].pk,
            ],
            'page_permissions-TOTAL_FORMS': '1',
            'page_permissions-MAX_NUM_FORMS': '1000',
            'page_permissions-MIN_NUM_FORMS': '0',
            'page_permissions-INITIAL_FORMS': '0',
            'page_permissions-0-DELETE': '',
            'page_permissions-0-permission_types': ['add', 'edit', 'publish', 'bulk_delete', 'lock'],
            'page_permissions-0-page': self.wagtail_site.root_page.pk,
            'document_permissions-TOTAL_FORMS': '1',
            'document_permissions-MAX_NUM_FORMS': '1000',
            'document_permissions-MIN_NUM_FORMS': '0',
            'document_permissions-INITIAL_FORMS': '0',
            'document_permissions-0-collection': '2',
            'document_permissions-0-permissions': [
                self.perm_map['add_document'].pk,
                self.perm_map['change_document'].pk,
            ],
            'document_permissions-0-DELETE': '',
            'image_permissions-TOTAL_FORMS': '1',
            'image_permissions-MAX_NUM_FORMS': '1000',
            'image_permissions-INITIAL_FORMS': '0',
            'image_permissions-MIN_NUM_FORMS': '0',
            'image_permissions-0-permissions': [
                self.perm_map['add_image'].pk,
                self.perm_map['change_image'].pk
            ],
            'image_permissions-0-collection': '2',
            'image_permissions-0-DELETE': '',
        }

    ############
    # TESTS
    ############

    def test_edit_group_happy_path_for_superuser(self):
        request = self.wagtail_factory.post('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        request.POST = self.happy_path_form_data

        # Generate a Group based on the happy path data.
        group = Group()
        form = MultitenantGroupForm(request.POST, instance=group, request=request)
        permission_panels = get_permission_panel_instances(request, group)
        form.is_valid()
        new_group = form.save()
        for panel in permission_panels:
            panel.save()

        # Now, edit the group and make sure the edits come through correctly.
        request = self.wagtail_factory.post('/')
        request.user = self.superuser
        request.site = self.wagtail_site
        request.POST = copy.deepcopy(self.happy_path_form_data)
        # Add "add_redirect" and remove "change_user".
        request.POST['permissions'] = [
            self.perm_map['change_settings'].pk,
            self.perm_map['change_group'].pk,
            self.perm_map['access_admin'].pk,
            self.perm_map['add_redirect'].pk,
        ]
        # Remove publish and lock permissions.
        request.POST['page_permissions-0-permission_types'] = ['add', 'edit', 'bulk_delete']
        # Remove permission to change documents, but leave image_permissions unchanged.
        request.POST['image_permissions-INITIAL_FORMS'] = 1
        request.POST['document_permissions-INITIAL_FORMS'] = 1
        request.POST['document_permissions-0-permissions'] = [self.perm_map['add_document'].pk]

        form = MultitenantGroupForm(request.POST, instance=new_group, request=request)
        permission_panels = get_permission_panel_instances(request, new_group)

        valid = form.is_valid()
        self.assertTrue(valid)
        new_group = form.save()
        for panel in permission_panels:
            panel.save()

        self.assertEqual(new_group.name, request.POST['name'])

        perm_ids = set(perm.pk for perm in new_group.permissions.all())
        self.assertEqual(perm_ids, set(request.POST['permissions']))

        page_perm_codenames = set(perm.permission_type for perm in new_group.page_permissions.all())
        self.assertEqual(page_perm_codenames, set(request.POST['page_permissions-0-permission_types']))

        for collection_perm in new_group.collection_permissions.all():
            self.assertEqual(collection_perm.collection.pk, self.wagtail_collection.pk)
        collection_perm_ids = set(perm.permission.pk for perm in new_group.collection_permissions.all())
        self.assertEqual(
            collection_perm_ids,
            set(request.POST['document_permissions-0-permissions'] + request.POST['image_permissions-0-permissions'])
        )

    def test_edit_group_view_GET(self):
        self.login('superuser')
        # First, test to make sure the routing works.
        response = self.client.get(
            reverse('wagtailusers_groups:edit', args=[self.wagtail_admins_group.pk]),
            HTTP_HOST=self.wagtail_site.hostname
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailusers/groups/edit.html')

        # Confirm that unpriviledged users can't access the view.
        self.login('wagtail_editor')
        response = self.client.get(
            reverse('wagtailusers_groups:edit', args=[self.wagtail_admins_group.pk]),
            HTTP_HOST=self.wagtail_site.hostname
        )
        self.assert_permission_denied_redirect(response)

        with Replacer() as r:
            # We can't dummy out the form until we start testing the view function directly, because the render
            # pipeline will crash if the form is a dummy.
            r.replace('wagtail_patches.views.groups.MultitenantGroupForm', self.form_dummy)
            r.replace('wagtail_patches.views.groups.get_permission_panel_instances', self.permission_panels_dummy)
            r.replace('wagtail_patches.views.groups.TemplateResponse', self.render_dummy)
            r.replace('wagtail.wagtailadmin.messages', self.messages_dummy)

            # Now, the real unit test requires us to call the view function directly, since the full request/response
            # workflow gets broken by our dummies.
            request = self.wagtail_factory.get('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site

            edit(request, self.wagtail_admins_group.pk)

            # Confirm that the view renders the correct tempalte with the correct context data.
            self.assertEqual(len(self.render_dummy.calls), 1)
            self.assertEqual(self.render_dummy.calls[0]['args'][1], 'wagtailusers/groups/edit.html')
            self.assertEqual(self.render_dummy.calls[0]['args'][2], {
                'group': self.wagtail_admins_group,
                'form': self.form_dummy.default_return,
                'permission_panels': self.permission_panels_dummy.default_return
            })

            # Confirm that the form is built correctly.
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(self.form_dummy.calls[0]['kwargs']['request'], request)
            self.assertEqual(len(self.permission_panels_dummy.calls), 1)
            self.assertEqual(self.permission_panels_dummy.calls[0]['args'][0], request)

            # Confirm that priviledged non-superusers can't access the edit view for a Group belonging to another site.
            response = edit(request, self.test_admins_group.pk)
            self.assertEqual(response.url, reverse('wagtailadmin_home'))

    def test_create_group_view_POST_invalid_data(self):
        with Replacer() as r:
            r.replace('wagtail_patches.views.groups.MultitenantGroupForm', self.form_dummy)
            r.replace('wagtail_patches.views.groups.messages', self.messages_dummy)
            r.replace('wagtail_patches.views.groups.get_permission_panel_instances', self.permission_panels_dummy)
            r.replace('wagtail_patches.views.groups.TemplateResponse', self.render_dummy)

            # Now, the real unit test requires us to call the view function directly, since the full request/responce
            # workflow gets broken by our dummies.
            request = self.wagtail_factory.post('/')
            request.user = self.superuser
            request.site = self.wagtail_site
            # Need to deepcopy this, since we'll be making changes that we don't want to get reflected in the original.
            request.POST = copy.deepcopy(self.happy_path_form_data)
            # Pass an empty Group name, so the form will pitch an error.
            request.POST['name'] = ''
            edit(request, self.test_admins_group.pk)

            # Confirm that the view code handles errors correctly.
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(len(self.form_dummy.default_return.is_valid.calls), 1)
            self.assertEqual(len(self.messages_dummy.error.calls), 1)

    def test_edit_group_view_POST_valid_data(self):
        with Replacer() as r:
            # By default, the form dummy's is_valid() returns False, so we need to change that for the valid data test.
            self.form_dummy.default_return.is_valid = Dummy(default_return=True)
            r.replace('wagtail_patches.views.groups.MultitenantGroupForm', self.form_dummy)
            r.replace('wagtail_patches.views.groups.messages', self.messages_dummy)
            r.replace('wagtail_patches.views.groups.get_permission_panel_instances', self.permission_panels_dummy)
            r.replace('wagtail_patches.views.groups.TemplateResponse', self.render_dummy)

            # Now, the real unit test requires us to call the view function directly, since the full request/responce
            # workflow gets broken by our dummies.
            request = self.wagtail_factory.post('/')
            request.user = self.wagtail_admin
            request.site = self.wagtail_site
            # Need to deepcopy this, since we'll be making changes that we don't want to get reflected in the original.
            request.POST = copy.deepcopy(self.happy_path_form_data)
            request.POST['name'] = 'Admoons'
            edit(request, self.wagtail_admins_group.pk)

            # Confirm that the view code handles valid data correctly.
            self.assertEqual(len(self.form_dummy.calls), 1)
            self.assertEqual(len(self.form_dummy.default_return.is_valid.calls), 1)
            self.assertEqual(len(self.form_dummy.default_return.save.calls), 1)
            self.assertEqual(len(self.perm_panel_dummy.is_valid.calls), 4)
            self.assertEqual(len(self.perm_panel_dummy.save.calls), 4)
            self.assertEqual(len(self.messages_dummy.error.calls), 0)
            self.assertEqual(len(self.messages_dummy.success.calls), 1)

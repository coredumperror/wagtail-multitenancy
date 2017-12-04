from django.contrib.auth.models import Permission, Group
from django.db import transaction
from django.utils.text import slugify
from django.utils.timezone import now
from wagtail.wagtailcore import hooks
from wagtail.wagtailcore.models import (
    GroupPagePermission, PAGE_PERMISSION_TYPES, GroupCollectionPermission, Collection, Site, Page
)

from core.utils import get_homepage_model
from features.models import Features


def apply_default_permissions(group, site, group_type):
    """
    Applies the default permissions to the given Group.
    group_type can be either 'admin' or 'editor'.
    """
    both_groups = ('admin', 'editor')
    # Allow both groups to access the Wagtail Admin.
    wagtail_admin_permission = Permission.objects.get(codename='access_admin')
    if group_type in both_groups:
        group.permissions.add(wagtail_admin_permission)

    # Only allow Admins to CRUD Users.
    if group_type == 'admin':
        group.permissions.add(Permission.objects.get(content_type__app_label='auth', codename='add_user'))
        group.permissions.add(Permission.objects.get(content_type__app_label='auth', codename='change_user'))
        group.permissions.add(Permission.objects.get(content_type__app_label='auth', codename='delete_user'))

    # Allow both groups to CRUD Redirects
    if group_type in both_groups:
        redirects = 'wagtailredirects'
        group.permissions.add(Permission.objects.get(content_type__app_label=redirects, codename='add_redirect'))
        group.permissions.add(Permission.objects.get(content_type__app_label=redirects, codename='change_redirect'))
        group.permissions.add(Permission.objects.get(content_type__app_label=redirects, codename='delete_redirect'))

    # Allow both groups to Add, Edit, Publish, and Lock the Site's Pages.
    if group_type in both_groups:
        for perm_type, short_label, long_label in PAGE_PERMISSION_TYPES:
            GroupPagePermission.objects.get_or_create(group=group, page=site.root_page, permission_type=perm_type)

    # For whatever reason, Delete permission isn't needed, as users with Edit can delete Images and Docs.
    add_img_perm    = Permission.objects.get(content_type__app_label='wagtailimages', codename='add_image')
    change_img_perm = Permission.objects.get(content_type__app_label='wagtailimages', codename='change_image')
    add_doc_perm    = Permission.objects.get(content_type__app_label='wagtaildocs', codename='add_document')
    change_doc_perm = Permission.objects.get(content_type__app_label='wagtaildocs', codename='change_document')

    # Give both groups full permissions on the Site's Image and Document Collections.
    collection = Collection.objects.get(name=site.hostname)
    if group_type in both_groups:
        GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=add_img_perm)
        GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=change_img_perm)
        GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=add_doc_perm)
        GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=change_doc_perm)

    homepage = site.root_page
    if group_type in both_groups:
        GroupPagePermission.objects.get_or_create(group=group, page=homepage, permission_type="add")
        GroupPagePermission.objects.get_or_create(group=group, page=homepage, permission_type="edit")
        GroupPagePermission.objects.get_or_create(group=group, page=homepage, permission_type="lock")

        GroupPagePermission.objects.filter(group=group, page=homepage, permission_type="bulk_delete").delete()

    # Execute all registered site_creator_default_permissions hooks. This allows apps that create their own
    # permissions to specify how said permissions should be configured by default on new Sites.
    # All implementations of site_creator_default_permissions must accept these positional parameters:
    # group: a django Group object
    # site: a Wagtail Site object
    # group_type: the string 'admin' or 'editor'.
    for func in hooks.get_hooks('site_creator_default_permissions'):
        func(group, site, group_type)


def create_site(owner, form_data):
    """
    Create a new Site with all the default content and content specified by various hooks.
    """
    # If anything in here happens to fail, make sure it ALL gets rolled back, so the db won't be corrupted
    # with partial Site creation results.
    with transaction.atomic():
        site = Site()
        # Generate the Site object from the form fields.
        site.hostname = form_data['hostname']
        site.site_name = form_data['site_name']

        # Generate the default Page that will act as the Homepage for this Site.
        home_page = get_homepage_model()()
        home_page.title = home_page.nav_title = generate_homepage_title(site.site_name)
        home_page.show_title = False
        home_page.slug = slugify(home_page.title)
        home_page.owner = owner
        home_page.show_in_menus = False
        home_page.latest_revision_created_at = now()
        home_page.first_published_at = now()
        home_page.show_title = False

        # We save the home_page by adding it as a child to Page 1, the ultimate root of the page tree.
        tree_root = Page.objects.first()
        home_page = tree_root.add_child(instance=home_page)
        site.root_page = home_page
        site.save()

        # Generate a blank Features for this Site.
        Features.objects.get_or_create(site=site)

        # Generate a Collection for this Site.
        collection = Collection()
        collection.name = site.hostname
        # Much like the homepage, we need to create this Collection as a child of the root Collection.
        collection_root = Collection.objects.first()
        collection_root.add_child(instance=collection)

        admins = Group.objects.create(name='{} Admins'.format(site.hostname))
        editors = Group.objects.create(name='{} Editors'.format(site.hostname))

        apply_default_permissions(admins, site, 'admin')
        apply_default_permissions(editors, site, 'editor')

        # Save the groups, and their permissions, to the database.
        admins.save()
        editors.save()

        # Execute all registered site_creator_default_pages hooks.
        # This hook allows apps to tell site_creator to create Pages within the page tree of each new Site.
        # All implementations of site_creator_default_pages must accept these parameters:
        # root_page: the root page of the newly created Site.
        for func in hooks.get_hooks('site_creator_default_pages'):
            func(site.root_page)

        return site


def generate_homepage_title(site_name):
    # I broke this out into a function because both create_site() and SiteCreationForm.clean_site_name() need it.
    return '{} Homepage'.format(site_name)

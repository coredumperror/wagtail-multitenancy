from django.contrib.auth.models import Group
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.vary import vary_on_headers
from wagtail.utils.pagination import paginate
from wagtail.wagtailadmin import messages
from wagtail.wagtailadmin.forms import SearchForm
from wagtail.wagtailadmin.utils import any_permission_required, permission_required, permission_denied
from wagtail.wagtaildocs.models import Document
from wagtail.wagtailimages.models import Image
from wagtail.wagtailusers.forms import GroupPagePermissionFormSet

from wagtail_patches.forms import (
    MultitenantGroupForm, multitenant_collection_member_permission_formset_factory
)


def get_permission_panel_classes():
    MultitenantGroupImagePermissionFormSet = multitenant_collection_member_permission_formset_factory(
        Image,
        [
            ('add_image', "Add", "Add/edit images you own"),
            ('change_image', "Edit", "Edit any image"),
        ],
        'wagtailimages/permissions/includes/image_permissions_formset.html'
    )
    MultitenantGroupDocumentPermissionFormSet = multitenant_collection_member_permission_formset_factory(
        Document,
        [
            ('add_document', "Add", "Add/edit documents you own"),
            ('change_document', "Edit", "Edit any document"),
        ],
        'wagtaildocs/permissions/includes/document_permissions_formset.html'
    )
    return [
            GroupPagePermissionFormSet,
            MultitenantGroupImagePermissionFormSet,
            MultitenantGroupDocumentPermissionFormSet,
        ]


def get_permission_panel_instances(request, group):
    """
    Note for testing: request.POST must contain the form data!
    """
    page_perms_cls, image_perms_cls, doc_perms_cls = get_permission_panel_classes()
    if request.method == 'POST':
        return [
            page_perms_cls(request.POST, instance=group),
            image_perms_cls(request.POST, instance=group, form_kwargs={'request': request}),
            doc_perms_cls(request.POST, instance=group, form_kwargs={'request': request}),
        ]
    else:
        return [
            page_perms_cls(instance=group),
            image_perms_cls(instance=group, form_kwargs={'request': request}),
            doc_perms_cls(instance=group, form_kwargs={'request': request}),
        ]


@any_permission_required('auth.add_group', 'auth.change_group', 'auth.delete_group')
@vary_on_headers('X-Requested-With')
def index(request):
    q = None
    is_searching = False

    if 'q' in request.GET:
        form = SearchForm(request.GET, placeholder='Search groups')
        if form.is_valid():
            q = form.cleaned_data['q']

            is_searching = True
            groups = Group.objects.filter(name__icontains=q)
    else:
        form = SearchForm(placeholder='Search groups')

    if not is_searching:
        groups = Group.objects.all()

    groups = groups.order_by('name')

    if 'ordering' in request.GET:
        ordering = request.GET['ordering']

        if ordering == 'name':
            groups = groups.order_by('name')
        elif ordering == '-name':
            groups = groups.order_by('-name')
    else:
        ordering = 'name'

    if not request.user.is_superuser:
        # Non-superusers should see only the Groups associated with the current Site.
        groups = groups.filter(name__startswith=request.site.hostname)

    unused, groups = paginate(request, groups)

    if request.is_ajax():
        return TemplateResponse(request, "wagtail_patches/groups/results.tpl", {
            'groups': groups,
            'is_searching': is_searching,
            'query_string': q,
            'ordering': ordering,
        })
    else:
        return TemplateResponse(request, "wagtail_patches/groups/index.html", {
            'search_form': form,
            'groups': groups,
            'is_searching': is_searching,
            'ordering': ordering,
            'query_string': q,
        })


@permission_required('auth.add_group')
def create(request):
    group = Group()
    if request.method == 'POST':
        form = MultitenantGroupForm(request.POST, instance=group, request=request)
        permission_panels = get_permission_panel_instances(request, group)
        if form.is_valid() and all(panel.is_valid() for panel in permission_panels):
            form.save()

            for panel in permission_panels:
                panel.save()

            messages.success(request, "Group '{0}' created.".format(group), buttons=[
                messages.button(reverse('wagtailusers_groups:edit', args=(group.id,)), 'Edit')
            ])
            return redirect('wagtailusers_groups:index')
        else:
            messages.error(request, 'The group could not be created due to errors.')
    else:
        form = MultitenantGroupForm(instance=group, request=request)
        permission_panels = get_permission_panel_instances(request, group)

    return TemplateResponse(request, 'wagtailusers/groups/create.html', {
        'form': form,
        'permission_panels': permission_panels,
    })


@permission_required('auth.change_group')
def edit(request, group_id):
    group = get_object_or_404(Group, pk=group_id)

    if not request.user.is_superuser:
        # Non-superusers cannot edit Groups that don't belong to the current Site.
        if not group.name.startswith(request.site.hostname):
            return permission_denied(request)

    if request.method == 'POST':
        form = MultitenantGroupForm(request.POST, instance=group, request=request)
        permission_panels = get_permission_panel_instances(request, group)
        if form.is_valid() and all(panel.is_valid() for panel in permission_panels):
            form.save()

            for panel in permission_panels:
                panel.save()

            messages.success(request, "Group '{0}' updated.".format(group), buttons=[
                messages.button(reverse('wagtailusers_groups:edit', args=[group.id]), 'Edit')
            ])
            return redirect('wagtailusers_groups:index')
        else:
            messages.error(request, 'The group could not be saved due to errors.')
    else:
        form = MultitenantGroupForm(instance=group, request=request)
        permission_panels = get_permission_panel_instances(request, group)

    return TemplateResponse(request, 'wagtailusers/groups/edit.html', {
        'group': group,
        'form': form,
        'permission_panels': permission_panels,
    })


@permission_required('auth.delete_group')
def delete(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not request.user.is_superuser:
        # Non-superusers cannot delete Groups that don't belong to the current Site.
        if not group.name.startswith(request.site.hostname):
            return permission_denied(request)

    if request.method == 'POST':
        group.delete()
        messages.success(request, "Group '{0}' deleted.".format(group.name))
        return redirect('wagtailusers_groups:index')

    return TemplateResponse(request, "wagtailusers/groups/confirm_delete.html", {
        'group': group,
    })

# Importing modules to replace something in their namespace
import django.contrib.auth.models
import taggit.managers
import wagtail.contrib.settings.views
import wagtail.wagtailadmin.forms
import wagtail.wagtailadmin.navigation
import wagtail.wagtailadmin.utils
import wagtail.wagtailadmin.views.pages
import wagtail.wagtailadmin.views.tags
import wagtail.wagtailadmin.views.home
import wagtail.wagtailcore.rich_text
import wagtail.wagtaildocs.forms
import wagtail.wagtaildocs.views.chooser
import wagtail.wagtaildocs.views.documents
import wagtail.wagtaildocs.views.multiple
import wagtail.wagtaildocs.views.serve
import wagtail.wagtailimages.forms
import wagtail.wagtailimages.views.chooser
import wagtail.wagtailimages.views.images
import wagtail.wagtailimages.views.multiple
import wagtail.wagtailsites.views

# Normal imports
from django import forms
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, router, connections
from django.db.models import Count, Q
from django.forms import modelform_factory
from django.http import BadHeaderError, Http404, StreamingHttpResponse
from django.http.response import HttpResponseForbidden, JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.utils import six
from django.utils.encoding import force_text
from django.utils.text import capfirst
from django.views.decorators.vary import vary_on_headers
from djunk.middleware import get_current_request, get_current_user
from logging import INFO, WARNING, ERROR, CRITICAL
from six.moves.urllib.parse import quote
from types import MethodType
from wagtail.contrib.settings.forms import SiteSwitchForm
from wagtail.contrib.settings.permissions import user_can_edit_setting_type
from wagtail.contrib.settings.views import get_model_from_url_params, get_setting_edit_handler
from wagtail.utils import sendfile_streaming_backend
from wagtail.utils.pagination import paginate
from wagtail.utils.sendfile import sendfile
from wagtail.wagtailadmin import messages, widgets
from wagtail.wagtailadmin.forms import (
    CollectionForm, BaseGroupCollectionMemberPermissionFormSet, SearchForm, PageViewRestrictionForm)
from wagtail.wagtailadmin.modal_workflow import render_modal_workflow
from wagtail.wagtailadmin.views.collections import Delete as CollectionDelete
from wagtail.wagtailcore import hooks
from wagtail.wagtailcore.models import (
    Collection, Site, GroupCollectionPermission, GroupPagePermission, logger as wagtailmore_models_logger,
    Page, PageRevision, PagePermissionTester)
from wagtail.wagtaildocs.forms import BaseDocumentForm
from wagtail.wagtaildocs.models import get_document_model, document_served
from wagtail.wagtaildocs.permissions import permission_policy as document_permission_policy
from wagtail.wagtailcore.rich_text import DbWhitelister, get_embed_handler, get_link_handler
from wagtail.wagtailimages import get_image_model
from wagtail.wagtailimages.fields import ALLOWED_EXTENSIONS
from wagtail.wagtailimages.forms import BaseImageForm, formfield_for_dbfield
from wagtail.wagtailimages.permissions import permission_policy as image_permission_policy
from wagtail.wagtailimages.views.images import permission_checker
from wagtail.wagtailimages.views.multiple import get_image_edit_form
from wagtail.wagtailusers.forms import BaseGroupPagePermissionFormSet
from wsgiref.util import FileWrapper
from unidecode import unidecode

from core.logging import logger, log_new_model, request_context_logging_processor
from core.models import OurImage
from core.models.utils import SiteSpecificTag


################################################################################################################
# Monkey patch Wagtail's Collection mechanism to prevent Collections created through the Site Creator from being
# renamed or deleted before their associated Site is deleted. This is necessary because several mechanisms
# assume that a Collection named "blah.oursites.com" will exist alongside the site hosted as "blah.oursites.com".
################################################################################################################
def collection_form_clean_name(self):
    if self.instance.name in [site.hostname for site in Site.objects.all()]:
        raise ValidationError('Collections named after Sites cannot be renamed.')
CollectionForm.clean_name = collection_form_clean_name


def collection_delete_get_context(self):
    context = super(CollectionDelete, self).get_context()
    collection_contents = self.get_collection_contents()

    if collection_contents:
        # collection is non-empty; render the 'not allowed to delete' response.
        self.template_name = 'wagtailadmin/collections/delete_not_empty.html'
        context['collection_contents'] = collection_contents

    if self.instance.name in [site.hostname for site in Site.objects.all()]:
        # collection is assocated with an existing Site that was created by site_creator;
        # render the "you must delete the Site first" response.
        self.template_name = 'wagtail_patches/collections/delete_site_exists.html'
        context['site_name'] = self.instance.name

    return context
CollectionDelete.get_context = collection_delete_get_context


def collection_delete_post(self, request, instance_id):
    self.instance = get_object_or_404(self.get_queryset(), id=instance_id)
    collection_contents = self.get_collection_contents()

    if collection_contents or self.instance.name in [site.hostname for site in Site.objects.all()]:
        # collection is non-empty or belongs to an existing site; refuse to delete it.
        return HttpResponseForbidden()

    self.instance.delete()
    messages.success(request, self.success_message.format(self.instance))
    return redirect(self.index_url_name)
CollectionDelete.post = collection_delete_post


################################################################################################################
# Monkey patch Wagtail's Collection Permission mechanism to make it log the creation of new permissions. We
# already log the deletion of permissions using signals, but the original mechanism uses bulk_create() for
# adding new ones, which doesn't send signals.
################################################################################################################
@transaction.atomic
def group_collection_permission_save(self):
    if self.instance.pk is None:
        raise Exception(
            "Cannot save a GroupCollectionMemberPermissionFormSet "
            "for an unsaved group instance"
        )

    # get a set of (collection, permission) tuples for all ticked permissions
    forms_to_save = [
        form for form in self.forms
        if form not in self.deleted_forms and 'collection' in form.cleaned_data
    ]

    final_permission_records = set()
    for form in forms_to_save:
        for permission in form.cleaned_data['permissions']:
            final_permission_records.add((form.cleaned_data['collection'], permission))

    # fetch the group's existing collection permission records for this model,
    # and from that, build a list of records to be created / deleted
    permission_ids_to_delete = []
    permission_records_to_keep = set()

    for cp in self.instance.collection_permissions.filter(
        permission__in=self.permission_queryset,
    ):
        if (cp.collection, cp.permission) in final_permission_records:
            permission_records_to_keep.add((cp.collection, cp.permission))
        else:
            permission_ids_to_delete.append(cp.id)

    self.instance.collection_permissions.filter(id__in=permission_ids_to_delete).delete()

    permissions_to_add = final_permission_records - permission_records_to_keep
    added_perms = GroupCollectionPermission.objects.bulk_create([
        GroupCollectionPermission(
            group=self.instance, collection=collection, permission=permission
        )
        for (collection, permission) in permissions_to_add
    ])

    # Here's the only difference from the original function (besides saving the return value from bulk_create()):
    for perm in added_perms:
        log_new_model(perm)
BaseGroupCollectionMemberPermissionFormSet.save = group_collection_permission_save


@transaction.atomic
def group_page_permission_save(self):
    if self.instance.pk is None:
        raise Exception(
            "Cannot save a GroupPagePermissionFormSet for an unsaved group instance"
        )

    # get a set of (page, permission_type) tuples for all ticked permissions
    forms_to_save = [
        form for form in self.forms
        if form not in self.deleted_forms and 'page' in form.cleaned_data
    ]

    final_permission_records = set()
    for form in forms_to_save:
        for permission_type in form.cleaned_data['permission_types']:
            final_permission_records.add((form.cleaned_data['page'], permission_type))

    # fetch the group's existing page permission records, and from that, build a list
    # of records to be created / deleted
    permission_ids_to_delete = []
    permission_records_to_keep = set()

    for pp in self.instance.page_permissions.all():
        if (pp.page, pp.permission_type) in final_permission_records:
            permission_records_to_keep.add((pp.page, pp.permission_type))
        else:
            permission_ids_to_delete.append(pp.pk)

    self.instance.page_permissions.filter(pk__in=permission_ids_to_delete).delete()

    permissions_to_add = final_permission_records - permission_records_to_keep
    added_perms = GroupPagePermission.objects.bulk_create([
        GroupPagePermission(
            group=self.instance, page=page, permission_type=permission_type
        )
        for (page, permission_type) in permissions_to_add
    ])

    # Here's the only difference from the original function (besides saving the return value from bulk_create()):
    for perm in added_perms:
        log_new_model(perm)
BaseGroupPagePermissionFormSet.save = group_page_permission_save


#################################################################################################################
# Monkey patch Wagtail's wagtail.core logger to make it include context information on every message
#################################################################################################################
def annotate_message(msg):
    """
    Annotate our log message with key/value pairs for:
        current username (if any)
        current site (if any)
        remote_ip (if any)
        whether the user is a superuser
    """
    # request_context_logging_processor() is written for use by structlog, but it also works when used like this.
    context = request_context_logging_processor(None, None, {})
    stringified_context = " ".join("{}={}".format(key, repr(context[key])) for key in sorted(context))
    msg = "{} {}".format(repr(msg), stringified_context)
    return msg


def patched_info(self, msg, *args, **kwargs):
    if self.isEnabledFor(INFO):
        self._log(INFO, annotate_message(msg), args, **kwargs)
# noinspection PyArgumentList
# We're patching an *instance* of the Logger class, rather than the Logger class itself.
# Thus, we need to use the MethodType class to turn patched_*() into instance methods.
wagtailmore_models_logger.info = MethodType(patched_info, wagtailmore_models_logger)


def patched_warning(self, msg, *args, **kwargs):
    if self.isEnabledFor(WARNING):
        self._log(WARNING, annotate_message(msg), args, **kwargs)
# noinspection PyArgumentList
wagtailmore_models_logger.warning = MethodType(patched_warning, wagtailmore_models_logger)


def patched_error(self, msg, *args, **kwargs):
    if self.isEnabledFor(ERROR):
        self._log(ERROR, annotate_message(msg), args, **kwargs)
# noinspection PyArgumentList
wagtailmore_models_logger.error = MethodType(patched_error, wagtailmore_models_logger)


def patched_critical(self, msg, *args, **kwargs):
    if self.isEnabledFor(CRITICAL):
        self._log(CRITICAL, annotate_message(msg), args, **kwargs)
# noinspection PyArgumentList
wagtailmore_models_logger.critical = MethodType(patched_critical, wagtailmore_models_logger)


#################################################################################################################
# Patch get_document_form() to return a form that excludes the Collection field for non-superusers.
# Patched from commit 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
def patched_get_document_form(model):
    fields = model.admin_form_fields
    if 'collection' not in fields:
        # Force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g adding the
        # document to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = list(fields) + ['collection']

    form_widgets = {
        'tags': widgets.AdminTagWidget,
        'file': forms.FileInput(),
    }
    # Monkey-patch: For non-superusers, replace the Collection field with a hidden input.
    if not get_current_request().user.is_superuser:
        form_widgets['collection'] = forms.HiddenInput()

    DocumentForm = modelform_factory(
        model,
        form=BaseDocumentForm,
        fields=fields,
        widgets=form_widgets
    )

    # Monkey-patch: Force non-superusers to use the current Site's Collection, no matter what they might have POSTed.
    def clean_collection(self):
        request = get_current_request()
        if not request.user.is_superuser:
            return Collection.objects.get(name=request.site.hostname)
        return self.cleaned_data['collection']
    DocumentForm.clean_collection = clean_collection

    return DocumentForm
# This monkey patch is special, because we're patching a raw function that gets imported directly into other
# namespaces besides the one where it's defined. We need to patch ALL those namespaces.
wagtail.wagtaildocs.forms.get_document_form = patched_get_document_form
wagtail.wagtaildocs.views.chooser.get_document_form = patched_get_document_form
wagtail.wagtaildocs.views.documents.get_document_form = patched_get_document_form
wagtail.wagtaildocs.views.multiple.get_document_form = patched_get_document_form


#################################################################################################################
# Patch get_document_multi_form() to return a form that excludes the Collection field for non-superusers.
# This also fixes a "bug" in Wagtail that prevents custom Document model fields from being settable on this form.
# Patched from commit 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
def patched_get_document_multi_form(model):
    form_widgets = {
        'tags': widgets.AdminTagWidget,
        'file': forms.FileInput(),
    }
    # Monkey-patch: For non-superusers, replace the Collection field with a hidden input.
    if not get_current_request().user.is_superuser:
        form_widgets['collection'] = forms.HiddenInput()

    DocumentMultiForm = modelform_factory(
        model,
        form=BaseDocumentForm,
        # Monkey-patch: Instead of using a fixed set of fields that excludes 'file', use ALL the fields except 'file'.
        # This lets users set additional flags like "On Campus Only" from this form.
        fields=[field for field in model.admin_form_fields if field != 'file'],
        widgets=form_widgets
    )

    # Monkey-patch: Force non-superusers to use the current Site's Collection, no matter what they might have POSTed.
    def clean_collection(self):
        request = get_current_request()
        if not request.user.is_superuser:
            return Collection.objects.get(name=request.site.hostname)
        return self.cleaned_data['collection']
    DocumentMultiForm.clean_collection = clean_collection

    return DocumentMultiForm
# This monkey patch is special, because we're patching a raw function that gets imported directly into other
# namespaces besides the one where it's defined. We need to patch ALL those namespaces.
wagtail.wagtaildocs.forms.get_document_multi_form = patched_get_document_multi_form
wagtail.wagtaildocs.views.multiple.get_document_multi_form = patched_get_document_multi_form


#################################################################################################################
# Monkey patch the wagtaildocs.views.chooser.chooser view to make it restrict the choosable documents to those in
# the current user's permitted Collections.
#################################################################################################################
def patched_document_chooser(request):
    if document_permission_policy.user_has_permission(request.user, 'add'):
        # Monkey-patch: user our patched version of get_document_form().
        DocumentForm = patched_get_document_form(get_document_model())
        # Monkey-patch: Set the intitial value for the Collection to the current Site's collection.
        # This is REQUIRED for non-superusers because django sets the initial value to 1 by default, which will always
        # throw an error because non-superusers dont have permission on the Root collection.
        initial = {'collection': Collection.objects.get(name=request.site.hostname)}
        uploadform = DocumentForm(user=request.user, initial=initial)
    else:
        uploadform = None

    documents = get_document_model().objects.all()

    # Allow hooks to modify the queryset.
    for hook in hooks.get_hooks('construct_document_chooser_queryset'):
        documents = hook(documents, request)

    q = None
    if 'q' in request.GET or 'p' in request.GET or 'collection_id' in request.GET:
        # This request was triggered from a search, pagination, or 'popular tags';
        # we will just render the results.html fragment.

        # This really just applies for superusers, since normal users are already getting their documents restricted
        # to the current Site's Collection.
        collection_id = request.GET.get('collection_id')
        if collection_id:
            documents = documents.filter(collection=collection_id)

        searchform = SearchForm(request.GET)
        if searchform.is_valid():
            q = searchform.cleaned_data['q']
            documents = documents.search(q)
            is_searching = True
        else:
            documents = documents.order_by('-created_at')
            is_searching = False

        _, documents = paginate(request, documents, per_page=10)

        return TemplateResponse(
            request,
            "wagtaildocs/chooser/results.html",
            {
                'documents': documents,
                'query_string': q,
                'is_searching': is_searching,
            }
        )
    else:
        searchform = SearchForm()

        # Monkey-patch: Only show the Collection dropdown to superusers.
        collections = None
        if request.user.is_superuser:
            collections = Collection.objects.all()
            # Don't show the dropdown if there's only one Collection.
            if len(collections) < 2:
                collections = None

        documents = documents.order_by('-created_at')
        _, documents = paginate(request, documents, per_page=10)

    return render_modal_workflow(
        request,
        'wagtaildocs/chooser/chooser.html',
        'wagtaildocs/chooser/chooser.js',
        {
            'documents': documents,
            'uploadform': uploadform,
            'searchform': searchform,
            'collections': collections,
            'is_searching': False,
        }
    )
wagtail.wagtaildocs.views.chooser.chooser = patched_document_chooser


#################################################################################################################
# Patch the wagtail.wagtaildocs.views.documents view to specify only the current site's collection, rather than
# a list of the collections the user is part of
#################################################################################################################
@permission_checker.require_any('add', 'change', 'delete')
@vary_on_headers('X-Requested-With')
def patched_documents_index(request):
    Document = get_document_model()

    # Get documents (filtered by user permission)
    documents = document_permission_policy.instances_user_has_any_permission_for(
        request.user, ['change', 'delete']
    )

    # Ordering
    if 'ordering' in request.GET and request.GET['ordering'] in ['title', '-created_at']:
        ordering = request.GET['ordering']
    else:
        ordering = '-created_at'
    documents = documents.order_by(ordering)

    # Filter by collection
    # Monkey-patch: Moved the collection filtering before the search because searching converts "documants" to an
    # ES5SearchResults that has no filter method. This doesn't break the original index because the UI doesn't let you
    # filter by collection and search at the same time.
    current_collection = None
    collection_id = request.GET.get('collection_id')
    # If the collection_id GET arg was set and you're a superuser, filter by the given collection.
    if collection_id and request.user.is_superuser:
        try:
            current_collection = Collection.objects.get(id=collection_id)
        except Collection.DoesNotExist:
            pass
        else:
            documents = documents.filter(collection=current_collection)
    # Non-superusers always get their documwnts filtered by the current Site's Collection.
    if not request.user.is_superuser:
        current_collection = Collection.objects.get(name=request.site.hostname)
        documents = documents.filter(collection=current_collection)

    # Search
    query_string = None
    if 'q' in request.GET:
        form = SearchForm(request.GET, placeholder="Search documents")
        if form.is_valid():
            query_string = form.cleaned_data['q']
            documents = documents.search(query_string)
    else:
        form = SearchForm(placeholder="Search documents")

    # Pagination
    _, documents = paginate(request, documents)

    # Monkey-patch: Only show the Collections dropdown to superusers.
    if request.user.is_superuser:
        collections = Collection.objects.all()
        if len(collections) < 2:
            collections = None
    else:
        # Set the collections to None so no dropdown Collection chooser is rendered
        collections = None

    # Create response
    if request.is_ajax():
        return render(request, 'wagtaildocs/documents/results.html', {
            'ordering': ordering,
            'documents': documents,
            'query_string': query_string,
            'is_searching': bool(query_string),
        })
    else:
        return render(request, 'wagtaildocs/documents/index.html', {
            'ordering': ordering,
            'documents': documents,
            'query_string': query_string,
            'is_searching': bool(query_string),

            'search_form': form,
            'popular_tags': multitenant_popular_tags_for_model(Document),
            'user_can_add': document_permission_policy.user_has_permission(request.user, 'add'),
            'collections': collections,
            'current_collection': current_collection,
        })
wagtail.wagtaildocs.views.documents.index = patched_documents_index


#################################################################################################################
# Patch the wagtail.wagtaildocs.views.multiple view to remove the collection chooser from the add view
#################################################################################################################
@permission_checker.require('add')
@vary_on_headers('X-Requested-With')
def patched_documents_multiple_add(request):
    DocumentForm = patched_get_document_form(get_document_model())
    DocumentMultiForm = patched_get_document_multi_form(get_document_model())

    # Monkey-patch: Superusers see all Collections. Others see none.
    collections_to_choose = Collection.objects.all() if request.user.is_superuser else None

    if request.method == 'POST':
        if not request.is_ajax():
            return HttpResponseBadRequest("Cannot POST to this view without AJAX")

        if not request.FILES:
            return HttpResponseBadRequest("Must upload a file")

        # Monkey-patch: Superusers can specify a Collection. Others automatically get the current Site's Collection.
        if request.user.is_superuser:
            collection_id = request.POST.get('collection')
        else:
            collection_id = Collection.objects.get(name=request.site.hostname).id

        # Build a form for validation
        form = DocumentForm({
            'title': request.FILES['files[]'].name,
            'collection': collection_id,
        }, {
            'file': request.FILES['files[]']
        }, user=request.user)

        if form.is_valid():
            # Save it
            doc = form.save(commit=False)
            doc.uploaded_by_user = request.user
            doc.file_size = doc.file.size
            doc.save()

            # Success! Send back an edit form for this document to the user
            return JsonResponse({
                'success': True,
                'doc_id': int(doc.id),
                'form': render_to_string('wagtaildocs/multiple/edit_form.html', {
                    'doc': doc,
                    'form': DocumentMultiForm(
                        instance=doc, prefix='doc-%d' % doc.id, user=request.user
                    ),
                }, request=request),
            })
        else:
            # Validation error
            return JsonResponse({
                'success': False,

                # https://github.com/django/django/blob/stable/1.6.x/django/forms/util.py#L45
                'error_message': '\n'.join(['\n'.join([force_text(i) for i in v]) for k, v in form.errors.items()]),
            })
    else:
        form = DocumentForm(user=request.user)

    return render(request, 'wagtaildocs/multiple/add.html', {
        'help_text': form.fields['file'].help_text,
        'collections': collections_to_choose,
    })

wagtail.wagtaildocs.views.multiple.add = patched_documents_multiple_add


#################################################################################################################
# Moneky patch the wagtailadmin.views.tags.autocomplete view to make it use our custom Tag model, instead of
# Taggit's default Tag model.
# rrollins 2017-5-22: This is actually a bug in Wagtail, but writing the fix is less-than-intuitive. I'm writing
# this monkey patch now with the intent of eventually removing it once I figure out how to fix Wagtail for real.
#################################################################################################################
def multitenant_autocomplete(request):
    term = request.GET.get('term', None)
    if term:
        tags = SiteSpecificTag.objects.filter(name__istartswith=term, site=request.site).order_by('name')
    else:
        tags = SiteSpecificTag.objects.none()
    return JsonResponse([tag.name for tag in tags], safe=False)

wagtail.wagtailadmin.views.tags.autocomplete = multitenant_autocomplete


#################################################################################################################
# Patch taggit.managers._TaggableManager._to_tag_model_instances() to make it take Sites into account when
# creating and re-using instances of SiteSpecificTag.
#################################################################################################################
def multitenant_to_tag_model_instances(self, tags):
    """
    Takes an iterable containing either strings, tag objects, or a mixture of both and returns set of tag objects.
    Monkey patched to take the current Wagtail Site object into account.
    """
    db = router.db_for_write(self.through, instance=self.instance)

    str_tags = set()
    tag_objs = set()

    for t in tags:
        if isinstance(t, self.through.tag_model()):
            tag_objs.add(t)
        elif isinstance(t, six.string_types):
            str_tags.add(t)
        else:
            raise ValueError(
                "Cannot add {0} ({1}). Expected {2} or str.".format(
                    t, type(t), type(self.through.tag_model())))
    case_insensitive = getattr(settings, 'TAGGIT_CASE_INSENSITIVE', False)
    manager = self.through.tag_model()._default_manager.using(db)

    # Get the current Site, so we can:
    # 1) Search for existing tags only within the current Site's list of tags.
    # 2) Ensure that new tags are created for the current Site.
    current_site = get_current_request().site

    if case_insensitive:
        # Some databases can do case-insensitive comparison with IN, which
        # would be faster, but we can't rely on it or easily detect it.
        existing = []
        tags_to_create = []

        for name in str_tags:
            try:
                tag = manager.get(name__iexact=name, site=current_site)
                existing.append(tag)
            except self.through.tag_model().DoesNotExist:
                tags_to_create.append(name)
    else:
        # If str_tags has 0 elements Django actually optimizes that to not
        # do a query.  Malcolm is very smart.
        existing = manager.filter(name__in=str_tags, site=current_site)
        tags_to_create = str_tags - set(t.name for t in existing)

    tag_objs.update(existing)

    for new_tag in tags_to_create:
        if case_insensitive:
            try:
                tag = manager.get(name__iexact=new_tag, site=current_site)
            except self.through.tag_model().DoesNotExist:
                tag = manager.create(name=new_tag, site=current_site)
                logger.info('tag.new', tag=new_tag)
        else:
            logger.info('tag.new', tag=new_tag)
            tag = manager.create(name=new_tag, site=current_site)

        tag_objs.add(tag)

    return tag_objs

taggit.managers._TaggableManager._to_tag_model_instances = multitenant_to_tag_model_instances


#################################################################################################################
# Patch the popular_tags_for_model method to remove the hostname prefix if it exists
#################################################################################################################
def multitenant_popular_tags_for_model(model, count=10):
    """
    Return a queryset of the most frequently used SiteSpecificTags used on this model on the current Site.
    """
    # NOTE TO DEVELOPERS: If this crashes in a test, you need to use Replacer to replace get_current_request() with
    # one that returns a fake request object with a 'site' property.
    current_site = get_current_request().site
    content_type = ContentType.objects.get_for_model(model)
    tags = (
        model.tags.through.tag_model().objects.filter(**{
            '{}__content_type'.format(model.tags.through.tag_relname()): content_type,
            'site': current_site,
        })
        .annotate(item_count=Count(model.tags.through.tag_relname()))
        .order_by('-item_count')[:count]
    )
    return tags

wagtail.wagtailadmin.utils.popular_tags_for_model = multitenant_popular_tags_for_model


#################################################################################################################
# Patch the get_image_form function to return a form that excludes the Collection field for non-superusers.
# Patched from commit 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
def patched_get_image_form(model):
    fields = model.admin_form_fields
    if 'collection' not in fields:
        # Force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g adding the
        # document to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = list(fields) + ['collection']

    form_widgets = {
        'tags': widgets.AdminTagWidget,
        'file': forms.FileInput(),
        'focal_point_x': forms.HiddenInput(attrs={'class': 'focal_point_x'}),
        'focal_point_y': forms.HiddenInput(attrs={'class': 'focal_point_y'}),
        'focal_point_width': forms.HiddenInput(attrs={'class': 'focal_point_width'}),
        'focal_point_height': forms.HiddenInput(attrs={'class': 'focal_point_height'}),
    }
    # Monkey-patch: For non-superusers, replace the Collection field with a hidden input.
    if not get_current_request().user.is_superuser:
        form_widgets['collection'] = forms.HiddenInput()

    ImageForm = modelform_factory(
        model,
        form=BaseImageForm,
        fields=fields,
        formfield_callback=formfield_for_dbfield,
        widgets=form_widgets
    )

    # Monkey-patch: Force non-superusers to use the current Site's Collection, no matter what they might have POSTed.
    def clean_collection(self):
        request = get_current_request()
        if not request.user.is_superuser:
            return Collection.objects.get(name=request.site.hostname)
        return self.cleaned_data['collection']
    ImageForm.clean_collection = clean_collection

    return ImageForm
# This monkey patch is special, because we're patching a raw function that gets imported directly into other
# namespsaces besides the one where it's defined. We need to patch ALL those namespaces.
wagtail.wagtailimages.forms.get_image_form = patched_get_image_form
wagtail.wagtailimages.views.chooser.get_image_form = patched_get_image_form
wagtail.wagtailimages.views.images.get_image_form = patched_get_image_form
wagtail.wagtailimages.views.multiple.get_image_form = patched_get_image_form


#################################################################################################################
# Monkey patch the wagtailimages.views.chooser.chooser view to make it restrict the choosable images to those in
# the current Site's Collection.
# Patched from commit: 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
def patched_image_chooser(request):
    if image_permission_policy.user_has_permission(request.user, 'add'):
        # Monkey-patch: user our patched version of get_image_form().
        ImageForm = patched_get_image_form(get_image_model())
        # Monkey-patch: Set the intitial value for the Collection to the current Site's collection.
        # This is REQUIRED for non-superusers because django sets the initial value to 1 by default, which will always
        # throw an error because non-superusers dont have permission on the Root collection.
        initial = {'collection': Collection.objects.get(name=request.site.hostname)}
        uploadform = ImageForm(user=request.user, initial=initial)
    else:
        uploadform = None

    images = get_image_model().objects.order_by('-created_at')

    # Allow hooks to modify the queryset.
    for hook in hooks.get_hooks('construct_image_chooser_queryset'):
        images = hook(images, request)

    q = None
    if 'q' in request.GET or 'p' in request.GET or 'tag' in request.GET or 'collection_id' in request.GET:
        # This request was triggered from a search, pagination, or 'popular tags';
        # we will just render the results.html fragment.

        # This really just applies for superusers, since normal users are already getting their images restricted
        # to the current Site's Collection.
        collection_id = request.GET.get('collection_id')
        if collection_id:
            images = images.filter(collection=collection_id)

        searchform = SearchForm(request.GET)
        if searchform.is_valid():
            q = searchform.cleaned_data['q']
            images = images.search(q)
            is_searching = True
        else:
            tag_name = request.GET.get('tag')
            if tag_name:
                images = images.filter(tags__name=tag_name)
            is_searching = False

        _, images = paginate(request, images, per_page=12)

        return TemplateResponse(
            request,
            "wagtailimages/chooser/results.html",
            {
                'images': images,
                'is_searching': is_searching,
                'query_string': q,
                'will_select_format': request.GET.get('select_format')
            }
        )
    else:
        # This is a normal chooser.
        searchform = SearchForm()

        # Monkey-patch: Only show the Collection dropdown to superusers.
        collections = None
        if request.user.is_superuser:
            collections = Collection.objects.all()
            # Don't show the dropdown if there's only one Collection.
            if len(collections) < 2:
                collections = None

        _, images = paginate(request, images, per_page=12)

    return render_modal_workflow(
        request,
        'wagtailimages/chooser/chooser.html',
        'wagtailimages/chooser/chooser.js',
        {
            'images': images,
            'uploadform': uploadform,
            'searchform': searchform,
            'is_searching': False,
            'query_string': q,
            'will_select_format': request.GET.get('select_format'),
            'popular_tags': multitenant_popular_tags_for_model(OurImage),
            'collections': collections,
        }
    )
wagtail.wagtailimages.views.chooser.chooser = patched_image_chooser


#################################################################################################################
# Patch the wagtail.wagtailimages.views.images index view to specify only the current site's collection, rather than
# a list of the collections the user is part of
#################################################################################################################
@permission_checker.require_any('add', 'change', 'delete')
@vary_on_headers('X-Requested-With')
def patched_images_index(request):
    Image = get_image_model()

    # Get images (filtered by user permission)
    images = image_permission_policy.instances_user_has_any_permission_for(
        request.user, ['change', 'delete']
    ).order_by('-created_at')

    # Filter by collection
    # Monkey-patch: Moved the collection filtering before the search because searching converts "images" to an
    # ES5SearchResults that has no filter method. This doesn't break the original index because the UI doesn't let you
    # filter by collection and search at the same time.
    current_collection = None
    collection_id = request.GET.get('collection_id')
    # If the collection_id GET arg was set and you're a superuser, filter by the given collection.
    if collection_id and request.user.is_superuser:
        try:
            current_collection = Collection.objects.get(id=collection_id)
        except Collection.DoesNotExist:
            pass
        else:
            images = images.filter(collection=current_collection)
    # Non-superusers always get their images filtered by the current Site's Collection.
    if not request.user.is_superuser:
        current_collection = Collection.objects.get(name=request.site.hostname)
        images = images.filter(collection=current_collection)

    # Search
    query_string = None
    if 'q' in request.GET:
        form = SearchForm(request.GET, placeholder="Search images")
        if form.is_valid():
            query_string = form.cleaned_data['q']
            images = images.search(query_string)
    else:
        form = SearchForm(placeholder="Search images")

    paginator, images = paginate(request, images)

    # Monkey-patch: Only show the Collections dropdown to superusers.
    if request.user.is_superuser:
        collections = Collection.objects.all()
        if len(collections) < 2:
            collections = None
    else:
        # Set the collections to None so no dropdown Collection chooser is rendered
        collections = None

    # Create response
    if request.is_ajax():
        return render(request, 'wagtailimages/images/results.html', {
            'images': images,
            'query_string': query_string,
            'is_searching': bool(query_string),
        })
    else:
        return render(request, 'wagtailimages/images/index.html', {
            'images': images,
            'query_string': query_string,
            'is_searching': bool(query_string),

            'search_form': form,
            'popular_tags': multitenant_popular_tags_for_model(Image),
            'collections': collections,
            'current_collection': current_collection,
            'user_can_add': image_permission_policy.user_has_permission(request.user, 'add'),
        })

wagtail.wagtailimages.views.images.index = patched_images_index


#################################################################################################################
# Patch the wagtail.wagtailimages.views.multiple.add() view to remove the collection chooser.
#################################################################################################################
@permission_checker.require('add')
@vary_on_headers('X-Requested-With')
def patched_images_multiple_add(request):
    ImageForm = patched_get_image_form(get_image_model())

    # Monkey-patch: Superusers see all Collections. Others see none.
    collections_to_choose = Collection.objects.all() if request.user.is_superuser else None

    if request.method == 'POST':
        if not request.is_ajax():
            return HttpResponseBadRequest("Cannot POST to this view without AJAX")

        if not request.FILES:
            return HttpResponseBadRequest("Must upload a file")

        # Monkey-patch: Superusers can specify a Collection. Others automatically get the current Site's Collection.
        if request.user.is_superuser:
            collection_id = request.POST.get('collection')
        else:
            collection_id = Collection.objects.get(name=request.site.hostname).id

        # Build a form for validation
        form = ImageForm({
            'title': request.FILES['files[]'].name,
            'collection': collection_id,
        }, {
            'file': request.FILES['files[]'],
        }, user=request.user)

        if form.is_valid():
            # Save it
            image = form.save(commit=False)
            image.uploaded_by_user = request.user
            image.file_size = image.file.size
            image.save()

            # Success! Send back an edit form for this image to the user
            return JsonResponse({
                'success': True,
                'image_id': int(image.id),
                'form': render_to_string('wagtailimages/multiple/edit_form.html', {
                    'image': image,
                    'form': get_image_edit_form(get_image_model())(
                        instance=image, prefix='image-%d' % image.id, user=request.user
                    ),
                }, request=request),
            })
        else:
            # Validation error
            return JsonResponse({
                'success': False,

                # https://github.com/django/django/blob/stable/1.6.x/django/forms/util.py#L45
                'error_message': '\n'.join(['\n'.join([force_text(i) for i in v]) for k, v in form.errors.items()]),
            })
    else:
        form = ImageForm(user=request.user)

    return render(request, 'wagtailimages/multiple/add.html', {
        'max_filesize': form.fields['file'].max_upload_size,
        'help_text': form.fields['file'].help_text,
        'allowed_extensions': ALLOWED_EXTENSIONS,
        'error_max_file_size': form.fields['file'].error_messages['file_too_large_unknown_size'],
        'error_accepted_file_types': form.fields['file'].error_messages['invalid_image'],
        'collections': collections_to_choose,
    })

wagtail.wagtailimages.views.multiple.add = patched_images_multiple_add


#################################################################################################################
# Patch the wagtailadmin.views.pages.search method to filter by the current site.
# Patched from commit 005e2e7a377337b8ed02b40e4d94b8597d5a8a9c (Add before_delete page hook)
#################################################################################################################
@vary_on_headers('X-Requested-With')
def single_site_search(request):
    pages = []
    q = None

    if 'q' in request.GET:
        form = SearchForm(request.GET)
        if form.is_valid():
            q = form.cleaned_data['q']

            pages = Page.objects.in_site(request.site).prefetch_related('content_type').search(q)
            paginator, pages = paginate(request, pages)
    else:
        form = SearchForm()

    if request.is_ajax():
        return render(request, "wagtailadmin/pages/search_results.html", {
            'pages': pages,
            'query_string': q,
            'pagination_query_params': ('q=%s' % q) if q else ''
        })
    else:
        return render(request, "wagtailadmin/pages/search.html", {
            'search_form': form,
            'pages': pages,
            'query_string': q,
            'pagination_query_params': ('q=%s' % q) if q else ''
        })

wagtail.wagtailadmin.views.pages.search = single_site_search


#################################################################################################################
# Monkey patch the wagtail.contrib.settings.views.edit view to make it deny non-superusers the priviledge of
# using it for any Site except the current one. Also, if the form is submitted successfully, the new view
# redirects to the "destination" in the GET args, if there is one.
#################################################################################################################
def multitenant_settings_edit(request, app_name, model_name, site_pk):
    model = get_model_from_url_params(app_name, model_name)
    if not user_can_edit_setting_type(request.user, model):
        raise PermissionDenied
    site = get_object_or_404(Site, pk=site_pk)

    if not request.user.is_superuser and site != request.site:
        raise PermissionDenied

    setting_type_name = model._meta.verbose_name

    instance = model.for_site(site)
    edit_handler_class = get_setting_edit_handler(model)
    form_class = edit_handler_class.get_form_class(model)

    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, instance=instance)

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "{setting_type} updated.".format(
                    setting_type=capfirst(setting_type_name),
                    instance=instance
                )
            )
            # If a destination was specified, redirect to there. Otherwise, redirect back to the form.
            destination = quote(request.POST.get('destination', ''))
            if destination:
                return redirect(destination)
            else:
                return redirect('wagtailsettings:edit', app_name, model_name, site.pk)
        else:
            # TODO: The destination gets lost when an error occurs. Not sure how to fix that, though. :(
            messages.error(request, "The setting could not be saved due to errors.")
            edit_handler = edit_handler_class(instance=instance, form=form)
    else:
        form = form_class(instance=instance)
        edit_handler = edit_handler_class(instance=instance, form=form)

    # Show a site switcher form if there are multiple sites
    site_switcher = None
    if Site.objects.count() > 1:
        site_switcher = SiteSwitchForm(site, model)

    return TemplateResponse(request, 'wagtailsettings/edit.html', {
        'opts': model._meta,
        'setting_type_name': setting_type_name,
        'instance': instance,
        'edit_handler': edit_handler,
        'form': form,
        'site': site,
        'site_switcher': site_switcher,
    })
wagtail.contrib.settings.views.edit = multitenant_settings_edit


################################################################################################################
# Monkey-patches the Document serve view to check for our custom PermissionedDocument states.
################################################################################################################
def document_serve(request, document_id, document_filename):
    Document = get_document_model()
    doc = get_object_or_404(Document, id=document_id)

    if doc.on_campus_only and not doc.user_is_on_campus(request):
        return HttpResponseForbidden("<h1>User must be on campus to view this document.</h1>")

    if doc.login_required and not doc.user_is_logged_in(request):
        return HttpResponseForbidden("<h1>User must be logged in to view this document.</h1>")

    # We want to ensure that the document filename provided in the URL matches the one associated with the considered
    # document_id. If not we can't be sure that the document the user wants to access is the one corresponding to the
    # <document_id, document_filename> pair.
    if doc.filename != document_filename:
        raise Http404('This document does not match the given filename.')

    # Send document_served signal
    document_served.send(sender=Document, instance=doc, request=request)

    try:
        local_path = doc.file.path
    except NotImplementedError:
        local_path = None

    if local_path:
        # Use wagtail.utils.sendfile to serve the file;
        # this provides support for mimetypes, if-modified-since and django-sendfile backends

        if hasattr(settings, 'SENDFILE_BACKEND'):
            return sendfile(request, local_path, attachment=True, attachment_filename=doc.filename)
        else:
            # Fallback to streaming backend if user hasn't specified SENDFILE_BACKEND
            return sendfile(
                request,
                local_path,
                attachment=True,
                attachment_filename=doc.filename,
                backend=sendfile_streaming_backend.sendfile
            )

    else:
        # We are using a storage backend which does not expose filesystem paths
        # (e.g. storages.backends.s3boto.S3BotoStorage).
        # Fall back on pre-sendfile behaviour of reading the file content and serving it
        # as a StreamingHttpResponse.
        wrapper = FileWrapper(doc.file)
        response = StreamingHttpResponse(wrapper, content_type='application/octet-stream')

        try:
            response['Content-Disposition'] = 'attachment; filename=%s' % doc.filename
        except BadHeaderError:
            # Unicode filenames can fail on Django <1.8, Python 2 due to
            # https://code.djangoproject.com/ticket/20889 - try with an ASCIIfied version of the name
            response['Content-Disposition'] = 'attachment; filename=%s' % unidecode(doc.filename)

        # FIXME: storage backends are not guaranteed to implement 'size'
        response['Content-Length'] = doc.file.size

        return response

wagtail.wagtaildocs.views.serve.serve = document_serve


#################################################################################################################
# Add a method to django.contrib.auth.User which strips the site hostname from
# the username, if it exists. We namespace our local users' usernames in the
# auth.User table by prefixing the user-visible username with the site hostname.
# We don't want that to be visible to Site admins in listings, etc.
#################################################################################################################
def de_namespaced_username(self):
    username = self.username
    user = get_current_user()
    # TODO: Is this hasattr check necessary?
    if hasattr(user, "is_superuser") and not user.is_superuser:
        # Show the unadulterated username to superusers
        request = get_current_request()
        if request:
            # This is called anytime we get a username, and sometimes
            # we might not be in a web request, so request will be None
            prefix = request.site.hostname + "-"
            if username.startswith(prefix):
                username = username[len(prefix):]
    return username

django.contrib.auth.models.User.de_namespaced_username = de_namespaced_username


#################################################################################################################
# Patch the wagtail.wagtailadmin.views.home.RecentEditsPanel.__init__ constructor to filter based on current site.
# This prevent users permissioned on multiple sites from seeing pages not belonging to the site they are
# currently on.
#################################################################################################################
def RecentEditsInit(self, request):
    self.request = request

    site_pages = Page.objects.in_site(request.site)
    site_keys = [p.pk for p in site_pages]

    # Last n edited pages
    last_edits = PageRevision.objects.raw(
        """
        SELECT wp.* FROM
            wagtailcore_pagerevision wp JOIN (
                SELECT max(created_at) AS max_created_at, page_id FROM
                    wagtailcore_pagerevision WHERE user_id = %s GROUP BY page_id ORDER BY max_created_at DESC LIMIT %s
            ) AS max_rev ON max_rev.max_created_at = wp.created_at ORDER BY wp.created_at DESC
         """, [
            get_user_model()._meta.pk.get_db_prep_value(self.request.user.pk, connections['default']),
            getattr(settings, 'WAGTAILADMIN_RECENT_EDITS_LIMIT', 5)
        ]
    )
    last_edits = list(last_edits)
    last_edits = [edit for edit in last_edits if edit.page.pk in site_keys]
    page_keys = [pr.page.pk for pr in last_edits]
    specific_pages = site_pages.filter(pk__in=page_keys)
    pages = {p.pk: p for p in specific_pages}
    self.last_edits = [
        [review, pages.get(review.page.pk)] for review in last_edits
    ]

wagtail.wagtailadmin.views.home.RecentEditsPanel.__init__ = RecentEditsInit


#################################################################################################################
# Patch the wagtail.wagtailadmin.navigation.get_pages_with_direct_explore_permission method to filter based on
# current site as well
#################################################################################################################
def get_explorer_pages(user):
    # Get all pages that the user has direct add/edit/publish/lock permission on
    if user.is_superuser:
        # superuser has implicit permission on the root node
        return Page.objects.filter(depth=1)
    else:
        return Page.objects.in_site(get_current_request().site).filter(
            group_permissions__group__in=user.groups.all(),
            group_permissions__permission_type__in=['add', 'edit', 'publish', 'lock']
        )

wagtail.wagtailadmin.navigation.get_pages_with_direct_explore_permission = get_explorer_pages


#################################################################################################################
# Patch the wagtail.wagtailcore.rich_text.DbWhiteLister clean_tag_node method to remove the div to p conversion.
# Patched from commit: 32f6f6e8f226057a3830f42cb485df0b8c1e5f6b (Use HalloPlugin media definitions to import...)
#################################################################################################################
# noinspection PyDecorator
@classmethod
def clean_tag_node(cls, doc, tag):
    if 'data-embedtype' in tag.attrs:
        embed_type = tag['data-embedtype']
        # fetch the appropriate embed handler for this embedtype
        embed_handler = get_embed_handler(embed_type)
        embed_attrs = embed_handler.get_db_attributes(tag)
        embed_attrs['embedtype'] = embed_type

        embed_tag = doc.new_tag('embed', **embed_attrs)
        embed_tag.can_be_empty_element = True
        tag.replace_with(embed_tag)
    elif tag.name == 'a' and 'data-linktype' in tag.attrs:
        # first, whitelist the contents of this tag
        for child in tag.contents:
            cls.clean_node(doc, child)

        link_type = tag['data-linktype']
        link_handler = get_link_handler(link_type)
        link_attrs = link_handler.get_db_attributes(tag)
        link_attrs['linktype'] = link_type
        tag.attrs.clear()
        tag.attrs.update(**link_attrs)
    else:
        super(DbWhitelister, cls).clean_tag_node(doc, tag)

wagtail.wagtailcore.rich_text.DbWhitelister.clean_tag_node = clean_tag_node


#################################################################################################################
# Patch the wagtail.wagtailadmin.forms.PageViewRestrictionForm class to filter gruops to only those available
# to the current site.
# Patched from commit: 59440c92f16e35d36395ef6e2911f52122fd175c (Update PageViewRestriction model to support...)
#################################################################################################################
def page_view_restriction_init(self, *args, **kwargs):
    super(PageViewRestrictionForm, self).__init__(*args, **kwargs)

    current_site = get_current_request().site

    self.fields['groups'].widget = forms.CheckboxSelectMultiple()
    self.fields['groups'].queryset = Group.objects.filter(name__istartswith=current_site.hostname)
    self.fields['groups'].choices = (
        (g.id, g.name.replace(current_site.hostname, '').strip())
        for g in Group.objects.filter(name__startswith=current_site.hostname)
    )

wagtail.wagtailadmin.forms.PageViewRestrictionForm.__init__ = page_view_restriction_init


#################################################################################################################
# Patch the wagtail.wagtailadmin.utils.users_with_page_permission function to exclude superusers by default. The
# only code that calls this function is wagtail.wagtailadmin.utils.users_with_page_permission, and in that
# context we don't want superusers to be emailed.
# Patched from commit: 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
# noinspection PyUnusedLocal
def patched_users_with_page_permission(page, permission_type, include_superusers=False):
    # Find GroupPagePermission records of the given type that apply to this page or an ancestor
    ancestors_and_self = list(page.get_ancestors()) + [page]
    perm = GroupPagePermission.objects.filter(permission_type=permission_type, page__in=ancestors_and_self)
    q = Q(groups__page_permissions__in=perm)

    # Include superusers
    if include_superusers:
        q |= Q(is_superuser=True)

    return get_user_model().objects.filter(is_active=True).filter(q).distinct()

wagtail.wagtailadmin.utils.users_with_page_permission = patched_users_with_page_permission


#################################################################################################################
# Patch the wagtail.wagtailcore.models.PermissionTester class to prevent the bulk_delete permission from
# affecting move operations. It breaks the ability to move subtrees around in the Sitemap.
# 2017-09-21 rrollins: I've put in a PR to make this change directly in wagtail. Hopefully they accept it.
#   https://github.com/wagtail/wagtail/pull/3873
# Patched from commit: 7175cd8d9b958e324176d3c3f072567b49591873 (Version bump to 1.12.2)
#################################################################################################################
def patched_can_move(self):
    return self.can_delete(ignore_bulk=True)
PagePermissionTester.can_move = patched_can_move


def patched_can_delete(self, ignore_bulk=False):
    if not self.user.is_active:
        return False
    if self.page_is_root:  # root node is not a page and can never be deleted, even by superusers
        return False

    if self.user.is_superuser:
        # superusers require no further checks
        return True

    # if the user does not have bulk_delete permission, they may only delete leaf pages
    if 'bulk_delete' not in self.permissions and not self.page.is_leaf() and not ignore_bulk:
        return False

    if 'edit' in self.permissions:
        # if the user does not have publish permission, we also need to confirm that there
        # are no published pages here
        if 'publish' not in self.permissions:
            pages_to_delete = self.page.get_descendants(inclusive=True)
            if pages_to_delete.live().exists():
                return False

        return True

    elif 'add' in self.permissions:
        pages_to_delete = self.page.get_descendants(inclusive=True)
        if 'publish' in self.permissions:
            # we don't care about live state, but all pages must be owned by this user
            # (i.e. eliminating pages owned by this user must give us the empty set)
            return not pages_to_delete.exclude(owner=self.user).exists()
        else:
            # all pages must be owned by this user and non-live
            # (i.e. eliminating non-live pages owned by this user must give us the empty set)
            return not pages_to_delete.exclude(live=False, owner=self.user).exists()

    else:
        return False
PagePermissionTester.can_delete = patched_can_delete

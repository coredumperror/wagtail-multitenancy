import re
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.vary import vary_on_headers
from django.utils.safestring import mark_safe
from wagtail.utils.pagination import paginate
from wagtail.wagtailadmin import messages
from wagtail.wagtailadmin.forms import SearchForm
from wagtail.wagtailadmin.utils import any_permission_required, permission_required, permission_denied
from wagtail.wagtailusers.views.users import add_user_perm, change_user_perm, delete_user_perm

from core.logging import logger
from core.utils import user_is_member_of_site
from ..forms import (
    LDAPUserCreateForm, LDAPUserEditForm, LocalUserCreateForm, LocalUserEditForm, LocalUserAdminResetPasswordForm
)


@any_permission_required(add_user_perm, change_user_perm, delete_user_perm)
@vary_on_headers('X-Requested-With')
def index(request):
    q = None
    is_searching = False

    if 'q' in request.GET:
        form = SearchForm(request.GET, placeholder='Search users')
        if form.is_valid():
            q = form.cleaned_data['q']
            is_searching = True
            filter_conditions = Q()
            special_conditions = Q()

            # Strip out quotes, since we're not doing an intelligent search. Just a quick and dirty filter.
            q = re.sub(r'''["']''', '', q)

            # Loop through each keyword in the query string, treating special keywords like "group:*"
            # differently from regular search terms.
            for keyword in q.split():
                if keyword.startswith('group:'):
                    keyword = keyword.replace('group:', '')
                    if request.user.is_superuser and re.match('superusers?$', keyword):
                        # Only superusers can search for superusers.
                        special_conditions &= Q(is_superuser=True)
                    else:
                        special_conditions &= Q(groups__name__icontains=keyword)
                elif request.user.is_superuser and re.match('superusers?$', keyword):
                    # Only superusers can search for superusers.
                    special_conditions &= Q(is_superuser=True)
                else:
                    # Match the Users' info fields against each of the search terms.
                    filter_conditions |= Q(username__icontains=keyword)
                    filter_conditions |= Q(first_name__icontains=keyword)
                    filter_conditions |= Q(last_name__icontains=keyword)
                    filter_conditions |= Q(email__icontains=keyword)

            # The filter_conditions are all OR'd together, but the special_conditions are AND'd with each other,
            # and must also be AND'd with the entire group of filter_conditions at once.
            # This lets a user search for e.g. "group:editors malek" and get only Editors who match "malek", instead
            # of all the Editors and all the maleks.
            users = get_user_model().objects.filter(filter_conditions).filter(special_conditions).distinct()
    else:
        form = SearchForm(placeholder='Search users')

    if not is_searching:
        users = get_user_model().objects.all()

    if 'ordering' in request.GET:
        ordering = request.GET['ordering']
        # "name" ordering is special, since it's not a real order_by() parameter.
        if ordering == 'name':
            users = users.order_by('last_name', 'first_name')
        elif ordering == '-name':
            users = users.order_by('-last_name', '-first_name')
        else:
            users = users.order_by(ordering)
    else:
        # If no ordering is specified, sort by name.
        users = users.order_by('last_name', 'first_name')
        ordering = 'name'

    if not request.user.is_superuser:
        # Non-superusers should see only non-superusers who belong to Groups associated with the current Site.
        # We need the distinct() because otherwise a user who belongs to multiple Groups will be duplicated.
        users = users.filter(groups__name__startswith=request.site.hostname).filter(is_superuser=False).distinct()

    unused, users = paginate(request, users)

    context = {
        'users': users,
        'is_searching': is_searching,
        'query_string': q,
        'ordering': ordering,
    }
    if request.is_ajax():
        return TemplateResponse(request, 'wagtail_patches/users/results.tpl', context)
    else:
        context['search_form'] = form
        return TemplateResponse(request, 'wagtail_patches/users/index.html', context)


@permission_required(add_user_perm)
def create(request):
    if request.method == 'POST':
        form = LDAPUserCreateForm(request, request.POST)
        if form.is_valid():
            user = form.save()
            # Users log in with their LDAP credentials, so their Django passwords never matter.
            user.set_unusable_password()
            messages.success(request, "User '{0}' created.".format(user), buttons=[
                messages.button(reverse('wagtailusers_users:edit', args=[user.pk]), 'Edit')
            ])
            return redirect('wagtailusers_users:index')
        else:
            messages.error(request, 'The user could not be created due to errors.')
    else:
        form = LDAPUserCreateForm(request)

    return TemplateResponse(request, 'wagtail_patches/users/create.html', {'form': form})


@permission_required(add_user_perm)
def create_local(request):
    if request.method == 'POST':
        form = LocalUserCreateForm(request, request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "Local User '{0}' created.".format(user), buttons=[
                messages.button(reverse('wagtailusers_users:edit', args=[user.pk]), 'Edit')
            ])
            return redirect('wagtailusers_users:index')
        else:
            messages.error(request, 'The user could not be created due to errors.')
    else:
        form = LocalUserCreateForm(request)

    return TemplateResponse(request, 'wagtail_patches/users/create_local.html', {'form': form})


@permission_required(change_user_perm)
def edit(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)

    if not request.user.is_superuser:
        # Non-supusers cannot edit superusers, and cannot edit Users who don't belong to the current site.
        if user.is_superuser or not user_is_member_of_site(user, request.site):
            return permission_denied(request)

    # We differentiate local Users from LDAP Users by checking if they have a usable password (LDAP Users don't).
    if user.has_usable_password():
        form_class = LocalUserEditForm
    else:
        form_class = LDAPUserEditForm

    if request.method == 'POST':
        form = form_class(request, user, request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "User '{0}' updated.".format(user), buttons=[
                messages.button(reverse('wagtailusers_users:edit', args=[user.pk]), 'Edit')
            ])
            return redirect('wagtailusers_users:index')
        else:
            messages.error(request, 'The user could not be saved due to errors.')
    else:
        form = form_class(request, user)

    return TemplateResponse(request, 'wagtail_patches/users/edit.html', {
        'user': user,
        'form': form,
        'requestor_is_superuser': request.user.is_superuser
    })


@permission_required(change_user_perm)
def admin_reset_password(request, username):
    user = get_object_or_404(get_user_model(), username=username)
    if request.method == 'GET':
        form = LocalUserAdminResetPasswordForm()
    elif request.method == 'POST':
        form = LocalUserAdminResetPasswordForm(request.POST)
        if form.is_valid():
            form.save(request)
            msg = "{} {} ({}) has been sent an email with a link that will let them reset their password.".format(
                user.first_name, user.last_name, user.username
            )
            messages.success(request, mark_safe(msg))
            return redirect(reverse('wagtailusers_users:index'))

    return TemplateResponse(request, 'wagtail_patches/users/admin_reset_password.html', {
        'form': form,
        'user': user,
    })


@permission_required(change_user_perm)
def remove_ldap_user(request, user_id):
    if hasattr(request, 'site'):
        if request.method == 'GET':
            user = get_object_or_404(get_user_model(), pk=user_id)
            site_hostname = request.site.hostname
            for group_name in ['Admins', 'Editors']:
                g = Group.objects.get(name="{} {}".format(site_hostname, group_name))
                g.user_set.remove(user)
            msg = "{} {} ({}) no longer has admin rights on {}.".format(
                user.first_name, user.last_name, user.username, site_hostname
            )
            messages.success(request, mark_safe(msg))
            logger.info('user.ldap.disabled-for-site', target_user=user.username)
    else:
        msg = "You must be on a particular site to remove an LDAP user."
        messages.error(request, mark_safe(msg))
    return redirect(reverse('wagtailusers_users:index'))

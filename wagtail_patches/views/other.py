from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, REDIRECT_FIELD_NAME, login as auth_login, views as auth_views
from django.contrib.sites.shortcuts import get_current_site
from django.http.response import HttpResponseRedirect
from django.shortcuts import redirect, resolve_url
from django.template.response import TemplateResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.http import is_safe_url
from wagtail.wagtailadmin.views.account import password_reset_enabled

from core.logging import logger
from wagtail_patches.forms import MultitenantLoginForm


@sensitive_post_parameters()
@csrf_protect
@never_cache
def login(request):
    # Since we're not logged in yet, get_logger()'s logger will not be bound
    # with the username, so we add that here.
    if request.user.is_authenticated and request.user.has_perm('wagtailadmin.access_admin'):
        # User is already logged in. Just redirect them to wagtail home.
        return redirect('wagtailadmin_home')
    else:
        # This code is adapted from django.contrib.auth.login(), to allow us to log login successes and failures.
        username = request.POST.get(get_user_model().USERNAME_FIELD)
        redirect_to = request.POST.get(REDIRECT_FIELD_NAME, request.GET.get(REDIRECT_FIELD_NAME, ''))

        if request.method == 'POST':
            form = MultitenantLoginForm(request, data=request.POST)
            if form.is_valid():
                # Ensure the user-originating redirection url is safe.
                if not is_safe_url(url=redirect_to, allowed_hosts=[request.get_host()]):
                    redirect_to = resolve_url(settings.LOGIN_REDIRECT_URL)

                # Okay, security check complete. Log the user in.
                auth_login(request, form.get_user())
                # Normally we wouldn't need to override the username here, because request.user is now a real User, but
                # because a LocalUser's username is prefixed with their Site's hostname, we log the username string
                # they actually logged in with.
                logger.info('auth.login.success', username=username)
                return HttpResponseRedirect(redirect_to)
            else:
                logger.warning('auth.login.failed', username=username)
        else:
            form = MultitenantLoginForm(request)

        current_site = get_current_site(request)

        context = {
            'form': form,
            REDIRECT_FIELD_NAME: redirect_to,
            'site': current_site,
            'site_name': current_site.name,
            'show_password_reset': password_reset_enabled(),
            'username_field': get_user_model().USERNAME_FIELD,
        }

        return TemplateResponse(request, 'wagtailadmin/login.html', context)


def logout(request):
    """
    This code is identical to wagtail.wagtailadmin.views.account.logout, except for the post-logout redirect.
    """
    # The next_page argument is here just to make the function return faster. We don't be using this response.
    response = auth_views.LogoutView.as_view()(request, next_page='/')
    logger.info('auth.logout')
    messages.success(request, 'You have logged out.')
    # By default, logging out will generate a fresh sessionid cookie. We want to use the
    # absence of sessionid as an indication that front-end pages are being viewed by a
    # non-logged-in user and are therefore cacheable, so we forcibly delete the cookie here.
    response.delete_cookie(settings.SESSION_COOKIE_NAME, settings.SESSION_COOKIE_PATH, settings.SESSION_COOKIE_DOMAIN)

    # HACK: pretend that the session hasn't been modified, so that SessionMiddleware
    # won't override the above and write a new cookie.
    request.session.modified = False

    # Just in case something is messed up with the Site's settings, avoid a crash.
    try:
        alias_count = request.site.settings.aliases.count()
    except:
        alias_count = 0

    # If we can get the referer, we use it as long as it's not an admin page (which would redirect back to the
    # login prompt). The user's already there, so we know it won't give a cert error.
    referer = request.META.get('HTTP_REFERER')
    if referer and '/admin/' not in referer:
        redirect_url = referer
    elif alias_count == 1:
        # If there is exactly one alias, redirect to the homepage of that domain.
        alias = request.site.settings.aliases.first()
        redirect_url = 'http://{}'.format(alias.domain)
    else:
        # We can't know which to pick among multiple aliases, so we fall back on the homepage of the canonical hostname.
        redirect_url = 'http://{}'.format(request.site.hostname)

    return HttpResponseRedirect(redirect_url)

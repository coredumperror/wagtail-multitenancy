from django import template
from django.utils.html import format_html
from wagtail.wagtailadmin.navigation import get_pages_with_direct_explore_permission

register = template.Library()


@register.simple_tag()
def render_site_specific_groups(user, request):
    """
    Returns the names of the User's groups which are associated with the current site, joined by <br>. The hostname is
    stripped from the Group names, just like in the Create/Edit forms (this isn't done for superusers). Superuser
    accounts also get the fake group "Superusers" added to their group list.
    """
    groups = []
    if user.is_superuser:
        groups.append('Superusers')

    if request.user.is_superuser:
        groups.extend(g.name for g in user.groups.all())
    else:
        groups.extend(
            group.name.replace(request.site.hostname, '').strip()
            for group
            in user.groups.filter(name__startswith=request.site.hostname)
        )

    # That extra space is included for debugging purposes. Without it, when our HTML parser strips the <br>, the Group
    # names get concatinated with no space between them.
    return format_html('<br> '.join(groups))


@register.simple_tag()
def site_specific_group_name(group, request):
    """
    Returns the name of the given Group with the current Site's hostname stripped off (for non-superusers).
    """
    if request.user.is_superuser:
        return group.name
    else:
        return group.name.replace(request.site.hostname, '').strip()


@register.simple_tag(takes_context=True)
def page_explorable(context, page):
    """
    Tests whether a given user has permission for a page.
    """
    user = context['request'].user
    pages = get_pages_with_direct_explore_permission(user)
    return page in pages

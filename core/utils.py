import ldap
import re
from crequest.middleware import CrequestMiddleware
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import connection
from django.http import Http404
from django.utils.deconstruct import deconstructible
from django.utils.encoding import force_text
from django_auth_ldap.backend import LDAPSettings, LDAPBackend, _LDAPUser
from djunk.middleware import get_current_request
from storages.backends.s3boto3 import S3Boto3Storage
from wagtail.wagtailadmin.views.home import PagesForModerationPanel
from wagtail.contrib.settings.registry import registry
from wagtail.wagtailcore.models import Site, Page, Collection, UserPagePermissionsProxy

from core.logging import logger
from core.modeldict import model_to_dict

# Used for the "choices" param on StreamField blocks that can list a variable
# number of items
SHOW_CHOICES = [
    (3, 3),
    (4, 4),
    (5, 5),
    (6, 6),
    (7, 7),
    (10, 10),
    (15, 15),
    (20, 20),
    (25, 25),
]

BACKGROUND_COLORS = [
    (None,  'Transparent'),
    ('white', 'White'),
    ('black', 'Black'),
    ('orange', 'Orange'),
    ('ltgray', 'Light Gray'),
    ('midgray', 'Mid Gray'),
    ('darkergray', 'Dark Gray'),
    ('dkgray', 'Very Dark Gray'),
    ('olivegreen', 'Olive Green'),
    ('purple', 'Purple'),
    ('darkteal', 'Dark Teal'),
]

FOREGROUND_COLORS = [
    (None, 'Default'),
    ('dkgray', 'Dark Gray'),
    ('black', 'Black'),
    ('white', 'White')
]


class Stuff(object):
    """
    This class exists so that we can instantiate SiteHelper without an actual site.
    """

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class SiteHelper(object):
    """
    This wraps our wagtail.wagtailcore.models.Site model with helper functions
    that return our site Group and Collection objects.
    """

    def __init__(self, site):
        self.site = site

    @property
    def hostname(self):
        return self.site.hostname

    @property
    def site_name(self):
        return self.site.site_name

    @property
    def home_page(self):
        return Page.objects.get(pk=self.site.root_page.id).specific

    @property
    def collection(self):
        if isinstance(self.site, Stuff):
            return None
        else:
            return Collection.objects.get(name=self.site.hostname)

    @property
    def admins_group(self):
        return self.group('Admins')

    @property
    def editors_group(self):
        return self.group('Editors')

    def group(self, short_name):
        name = self.group_name(short_name)
        if not isinstance(self.site, Stuff):
            return Group.objects.get(name=name)
        else:
            return Stuff(name=name, pk=name)

    def group_name(self, short_name):
        return "{} {}".format(self.site.hostname, short_name)

    def local_username(self, username):
        return "{}-{}".format(self.site.hostname, username)

    def get_user(self, username):
        # First try getting the local user
        if isinstance(self.site, Stuff):
            raise get_user_model().DoesNotExist
        try:
            return get_user_model().objects.get(username=self.local_username(username))
        except get_user_model().DoesNotExist:
            return get_user_model().objects.get(username=username)

    def import_id(self, obj_id):
        return "{}-{}-{}".format(self.site.hostname, self.site.pk, obj_id)


class SiteSettings(object):
    """
    A Settings model that derives from this class will be the one returned by get_installed_site_settings_class().

    This class is only to be used by ONE instance of BaseSetting per installation. Only Apps that define a site type
    (e.g. our_sites) should derive their Settings model from this class, since only one of those will ever be
    installed.

    NOTE: For arcane implementation reasons, ALL classes that subclass SiteSettings MUST be named "Settings".
    """

    def to_dict(self):
        """
        Converts this SiteSettings object to a dictionary.
        """
        return model_to_dict(self)


def get_installed_site_settings_class():
    """
    Returns the first SiteSetting object found in the wagtail.contrib.settings registry. See SiteSettings for details.
    """
    for setting in registry:
        if issubclass(setting, SiteSettings):
            return setting
    return None


@deconstructible
class HostnameValidator(object):
    """
    Validates that the input doesn't match any existing Site's hostname or alias list.
    """

    def __call__(self, value):
        text_value = force_text(value)

        if Site.objects.filter(hostname=text_value).exists():
            raise ValidationError('This domain name is already in use by another Site.', 'invalid')

        return True


@deconstructible
class AliasValidator(object):
    """
    The SiteAlias model has its domain field set to unique, so it can validate correctly when adding aliases.
    But when adding a new Site, its hostname field isn't checked against SiteAlias's domain field.
    """

    def __call__(self, value):
        text_value = force_text(value)

        for site in Site.objects.all():
            try:
                if text_value in [alias.domain for alias in site.settings.aliases.all()]:
                    raise ValidationError('This domain name is already in use by another Site.', 'invalid')
            except ObjectDoesNotExist:
                # If there is a Site which doesn't have a SiteSettings (common during testing), we can safely skip this
                # check, since no settings means no aliases.
                pass

        return True


def get_alias_and_hostname_validators(site_creator=False):
    """
    Returns the list of validators that ensure the hostname is correctly formatted and not in use by another Site.

    site_creator - Pass True to include AliasValidator. This validator is only for use by the Site
    Creator, because it will always break validation if used when updating a SiteSetting.
    """
    regex_validator = RegexValidator(
        r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)+([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$",
        'Please enter a valid domain name, e.g. example.oursites.com.'
    )
    validators = [regex_validator, HostnameValidator()]
    if site_creator:
        validators.append(AliasValidator())
    return validators


class MissingHostException(Exception):
    pass


def match_site_to_request(request):
    """
    Find the Site object responsible for responding to this HTTP request object. Try in this order:

    * unique hostname
    * non-unique hostname + port
    * unique site alias

    If there is no matching hostname, hostname:port combination, or alias for any Site, a 404 is thrown.

    This function returns a tuple of (<match-type>, Site), where <match-type> can be 'hostname' or 'alias'.
    It also pre-selects the Site's settings, root_page, and features attributes, for performance reasons.
    """
    query = Site.objects.select_related('settings', 'root_page', 'features')
    try:
        hostname = request.META['HTTP_HOST'].split(':')[0]
        try:
            # Find a Site matching this specific hostname.
            return ['hostname', query.get(hostname=hostname)]
        except Site.MultipleObjectsReturned:
            # As there were more than one, try matching by port, too.
            port = int(request.META['SERVER_PORT'])
            # Site.DoesNotExist thrown from this get() call goes to the final except clause.
            return ['hostname', query.get(hostname=hostname, port=port)]
        except Site.DoesNotExist:
            # This except clause catches "no Site exists with this hostname", in which case we check if the
            # hostname matches an alias. Site.DoesNotExist thrown from this get() call goes to the final except clause.
            return ['alias', query.get(settings__aliases__domain=hostname)]
    except KeyError:
        # If the HTTP_HOST header is missing, this is probably a test, because any on-spec HTTP client must include it.
        # The spec says to throw a 400 if that rule is violated.
        raise MissingHostException()
    except Site.DoesNotExist:
        # This except clause catches "no Site exists with this hostname:port", "no Site exists with this alias".
        # In these cases we raise a 404, since no Site matches the parameters.
        raise Http404()


def get_domains_for_current_site():
    """
    Returns the list of domains associated with the current site. If there is no current site, returns empty list.
    """
    request = get_current_request()
    site = request.site if request else None
    alias_domains = []
    if site:
        alias_domains.append(site.hostname)
        try:
            alias_domains = [alias.domain for alias in site.settings.aliases.all()]
        except:
            # This is a generic "except" because core can't know which settings class's DoesNotExist might get thrown.
            pass
    return alias_domains


def domain_erase(domains, text):
    """
    Removes all instances of the specified domains from the links in the given text.
    """
    # Create a regular expression from the domains, e.g. (https?://blah\.com|https?://www\.blue\.com).
    regex = "({})".format("|".join("https?://{}".format(re.escape(domain)) for domain in domains))
    # Replace each match with an empty string.
    return re.sub(regex, '', text)


def get_page_tree(request, max_depth=3):
    """
    Returns the menu tree as a "depth list", a list of lists of each level of the tree.
    Pass the return value of this function into the core/menus/desktop.tpl template, and it will render a <ul> tree.

    By default, this function returns the first three levels of the menu tree for the current site. But you can pass
    in max_depth to change the level upon which the menu terminates.

    If retrieveing the menu tree for the purposes of building the sitemap, this function will return ALL the pages
    below and icluding the current Site's rootpage, instead of just the live, on-menu pages that descend from it.
    """
    # Build the default query that will be used by both menu and sitemap.
    pages = Page.objects.order_by('path').specific()

    # The menu needs only live, on-menu pages below the homepage (so we can't use in_site()), up to a specified depth.
    pages = pages.descendant_of(request.site.root_page, inclusive=False).filter(show_in_menus=True, live=True)
    # The Root page and the Site's homepage live at depths 1 and 2, which is why we add 2 to max_depth.
    pages = pages.filter(depth__lte=max_depth+2)

    # Add the ultimate root page to the queryset. We need it for the depth_list algorithm.
    pages = pages | Page.objects.filter(depth=1)

    # Turn 'pages' into a tree structure:
    #     tree_node = (page, children)
    #     where 'children' is a list of tree_nodes.
    # Algorithm:
    # Maintain a list that tells us, for each depth level, the last page we saw at that depth level.
    # Since our page list is ordered by path, we know that whenever we see a page
    # at depth d, its parent must be the last page we saw at depth (d-1), and so we can
    # find it in that list.

    # Start with a dummy node for depth=0, so we don't need to special-case the addition of the first node.
    depth_list = [(None, [])]

    for page in pages:
        # When building the menu, we need to treat the top of the tree as if it were depth=2, because we're pretending
        # that the homepage doesn't exist, and that its children are actually children of the Root node.
        # So we subtract 1 from the real depth, unless that would be < 1.
        depth = max(page.depth - 1, 1)

        # Create a node for this page.
        node = (page, [])
        # Retrieve the parent from depth_list.
        try:
            parent_node, children = depth_list[depth - 1]
        except IndexError:
            # No parent exists for this page. This can happen when the first page at a certain depth is left off the
            # menu, but it has children that weren't left off. The current 'page' is one of those children, so it
            # doesn't belong in the depth_list.
            continue

        # If there is already a parent node to which this child might belong, confirm that it's actually this child's
        # parent. Like the try/except above, this is another way to skip children of non-menu parents.
        if parent_node is not None:
            if page.path.startswith(parent_node.path):
                children.append(node)

        # Add the new node to depth_list.
        try:
            depth_list[depth] = node
        except IndexError:
            # An exception here means that this node is one level deeper than any we've seen so far
            depth_list.append(node)

    # We've built up the depth_list by taking advantage of Python's "multiple names for the same list" functionality,
    # and some clever hackery with changing which element of depth_list is in which slot. Every element except
    # depth_list[1] was just a placeholder to serve the algorithm, though.
    # Now we need to take just depth_list[1]'s children, because we don't want the Root node in our menu.
    try:
        return depth_list[1][1]
    except IndexError:
        # What, we don't even have a root node? Fine, just return an empty list...
        return []


def get_homepage_model():
    """
    Returns the model class specified as the homepage model in the django settings.
    """
    return apps.get_model(settings.HOMEPAGE_MODEL)


def search_ldap_for_user(username):
    """
    Connects to LDAP using the settings and credentials defined for django_auth_ldap, then searches for a
    user matching the given username.

    Returns None if the user isn't found in LDAP, or tuple of (user_dn, ldap_attrs_dict) if it is.
    """
    # This is pretty gnarly, but the way that django_auth_ldap's got all its LDAP code split up across its
    # various classes, this is probably much less nasty than trying to do it more directly.
    ldap_user = _LDAPUser(LDAPBackend(), username=username.strip())
    results = LDAPSettings().USER_SEARCH.execute(ldap_user.connection, {'user': username})
    if len(results) == 1:
        return results[0]
    return None


def user_is_member_of_site(user, site):
    """
    Returns True if the given User is the member of a Group associated with the given Site.
    """
    return user.groups.filter(name__startswith=site.hostname).exists()


def populate_user_from_ldap(user):
    """
    Populate the given User object's personal info from LDAP.
    """
    try:
        _, ldap_attrs = search_ldap_for_user(user.username)
        user.first_name = ldap_attrs['givenName'][0]
        user.last_name = ldap_attrs['sn'][0]
        user.email = ldap_attrs['CAPPrimaryEmail'][0]
    except (IndexError, KeyError, TypeError, ldap.LDAPError) as err:
        # If any of these attrs are missing, or anything goes wrong, fail gracefully instead of crashing.
        # These attrs are not essential, and will be updated if possible the next time this User is saved.
        logger.error(
            'user.update_from_ldap.failed',
            target_user=user.username,
            reason="{}: {}".format(err.__class__.__name__, err)
        )
    else:
        logger.info(
            'user.update_from_ldap.success',
            target_user=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email
        )


def page_is_off_menu(page, request):
    """
    Determines if this page should be considered "off the menu" due to having an ancestor that's off it.
    """
    # "page.pk > 1" is a sanity check to make sure we don't infinite loop or crash under any circumstance.
    # The "page.pk is not None" check is for when the user is previewing an unsaved Page.
    while page.pk is not None and page.pk != request.site.root_page.pk and page.pk > 1:
        if not page.show_in_menus:
            return True
        page = page.get_parent()
    return False


def store_key_value_pair(key, value, expire_duration=None):
    """
    Records a key/vaue pair. If expire_duration is specified, the data will expire after that many seconds.
    """
    # Currently, we record key/value pairs in the cache. Maybe that'll change later? This function exists to abstract
    # that away.
    cache.set(key, value, expire_duration)


def get_key_value_pair(key, default=None):
    """
    Retrieve the value from the key/value store for the given key. If the value has expired, this function returns None,
    of the specified default.
    """
    # Currently, we record key/value pairs in the cache. Maybe that'll change later? This function exists to abstract
    # that away.
    return cache.get(key, default)


def set_fake_current_request(site, user):
    """
    Set's the "current request" to a FakeRequest object with the given Site and User.
    """
    # Create the "FakeRequest" class in-place and instantiate it.
    request = type('FakeRequest', (object,), {'site': site, 'user': user})()
    CrequestMiddleware.set_request(request)


# noinspection PyAbstractClass
class MultitenantBoto3Storage(S3Boto3Storage):
    """
    Subclasses S3Boto3Storage so we can customize it to our needs.
    """

    # Commented out until I have time to test if this actually provides a meaningful performance improvement.
    # # Altered for efficiency. Based on https://github.com/jschneier/django-storages/pull/352
    # def listdir(self, name):
    #     path = self._normalize_name(self._clean_name(name))
    #     # The path needs to end with a slash, but if the root is empty, leave
    #     # it.
    #     if path and not path.endswith('/'):
    #         path += '/'
    #
    #     directories = []
    #     files = []
    #     paginator = self.connection.get_paginator('list_objects_v2')
    #     pages = paginator.paginate(Bucket=self.bucket_name, Delimiter='/', Prefix=path)
    #     for page in pages:
    #         for entry in page['CommonPrefixes']:
    #             directories.append(posixpath.relpath(entry['Prefix'], path))
    #         for entry in page['Contents']:
    #             files.append(posixpath.relpath(entry['Key'], path))
    #     return directories, files


class MultitenantPagesForModerationPanel(PagesForModerationPanel):
    """
    Overrides PagesForModerationPanel to make it only include Pages that belong to the current Site.
    """
    name = 'wagtail_pages_for_moderation'
    # Places this panel before the Sitemap.
    order = 100

    def __init__(self, request):
        super(MultitenantPagesForModerationPanel, self).__init__(request)
        # Restrict the list to Pages on the current Site.
        self.page_revisions_for_moderation = (
            UserPagePermissionsProxy(request.user).revisions_for_moderation()
            .select_related('page', 'user')
            .filter(page__in=Page.objects.in_site(request.site))
            .order_by('-created_at')
        )


def get_current_site_from_context(context):
    """
    Returns the current Site from the 'request' in the given context. If the context has no 'request', the current Site
    is retrieved from the middleware.
    """
    try:
        current_site = context['request'].site
    except (KeyError, AttributeError):
        # request.site not available in the current context; get the request from middleware.
        current_site = get_current_request().site
    return current_site


def update_db_for_hostname_change(old_hostname, new_hostname):
    """
    This function updates all the tables in the database that utilize the string value of a Site's hostname.
    Those tables are:

    auth_group - We can't define a custom Group class, so we need to use their name as a connection to the related Site.
    wagtailcore_collection - Same as above.
    our_sites_permissioneddocument - The S3 file paths have to be Site-specific, so the 'file' field in this table
        needs to change when a Site's hostname changes. A different function must be called to affect that change in S3.
    core_ourimage - Same as above.
    core_ourrendition - Same as above.
    core_sitespecifictag - These do have an FK to the Site, but their slugs also have to be prefixed for uniqueness.
    """
    commands = [
        "UPDATE auth_group SET `name` = REPLACE(`name`, %s, %s)",
        "UPDATE wagtailcore_collection SET `name` = REPLACE(`name`, %s, %s)",
        "UPDATE our_sites_permissioneddocument SET `file` = REPLACE(`file`, %s, %s)",
        "UPDATE core_ourimage SET `file` = REPLACE(`file`, %s, %s)",
        "UPDATE core_ourrendition SET `file` = REPLACE(`file`, %s, %s)",
        "UPDATE core_sitespecifictag SET `slug` = REPLACE(`slug`, %s, %s)",
    ]
    with connection.cursor() as cursor:
        for command in commands:
            cursor.execute(command, [old_hostname, new_hostname])

from wagtail.wagtailcore import hooks

from .views import OurSiteViewSet


# NOTE (rrollins 2017-11-28): This is an undocummented hook, so I doubt we're guaranteed that it will continue to exist.
@hooks.register('register_admin_viewset')
def register_our_viewset():
    """
    This overrides the default ViewSet from wagtailsites with one that presents our forms for adding/editing Sites.
    """
    return OurSiteViewSet('wagtailsites', url_prefix='sites')

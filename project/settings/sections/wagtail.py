#################################################################
# Wagtail Config
#################################################################
from djunk.utils import getenv

# Display usage count on an image's edit page.
WAGTAIL_USAGE_COUNT_ENABLED = True
# Don't forcibly append slashes to the ends of URLs. Users can still reach each URL with a trailing slash, but it's
# not needed, and no redirects will be issued just to add a useless trailing slash.
WAGTAIL_APPEND_SLASH = False
APPEND_SLASH = False

# Elasticsearch
WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail.wagtailsearch.backends.elasticsearch5',
        'URLS': getenv('WAGTAIL_ELASTICSEARCH_URL').split(','),
        'INDEX': 'wagtail-multi',
        'TIMEOUT': 120,
        'ATOMIC_REBUILD': True,
    }
}

WAGTAIL_SITE_NAME = 'Our Sites'
WAGTAILIMAGES_IMAGE_MODEL = 'core.OurImage'
WAGTAILIMAGES_MAX_UPLOAD_SIZE = 30 * 1024 * 1024  # 30MB
WAGTAILDOCS_DOCUMENT_MODEL = 'our_sites.PermissionedDocument'

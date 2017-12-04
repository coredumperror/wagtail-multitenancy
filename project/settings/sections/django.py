#################################################################
# Django Config
#################################################################
import os
from djunk.utils import getenv

SETTINGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(SETTINGS_DIR)
BASE_DIR = os.path.dirname(PROJECT_DIR)

DEBUG = getenv('DEBUG', False)

INSTALLED_APPS = [
    'our_sites',

    # Multitenant apps.
    'core',
    'search',
    'site_creator',
    'theme',
    'robots_txt',
    'wagtail_patches',
    'sitemap',
    'features',

    # Multitenant dependencies.
    'jetstream',
    'djunk',
    'suit',
    'suit_ckeditor',
    'storages',
    # This is a custom fork of wagalytics that we've included in the repository itself.
    'wagalytics',
    'wagtailfontawesome',
    'wagtailerrorpages',
    'django_js_reverse',
    'django_bleach',
    'wagtailfacelift',
    'raven.contrib.django.raven_compat',

    # Wagtail apps.
    'wagtail.wagtailforms',
    'wagtail.wagtailredirects',
    'wagtail.wagtailembeds',
    'wagtail.wagtailsites',
    'wagtail.wagtailusers',
    'wagtail.wagtailsnippets',
    'wagtail.wagtaildocs',
    'wagtail.wagtailimages',
    'wagtail.wagtailsearch',
    'wagtail.wagtailadmin',
    'wagtail.wagtailcore',
    'wagtail.contrib.modeladmin',
    'wagtail.contrib.settings',
    'wagtail.contrib.wagtailroutablepage',

    # Wagtail dependencies.
    'modelcluster',
    'taggit',

    # Django apps.
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    # This one has to go first because it replaces django.middleware.common.CommonMiddleware, which has to be first.
    'djunk.middleware.SlashMiddleware',
    'core.middleware.MiddlewareIterationCounter',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',

    'core.middleware.MultitenantSiteMiddleware',
    'wagtail.wagtailredirects.middleware.RedirectMiddleware',

    # Enables the use of the get_current_request() and get_current_user() functions.
    'core.middleware.MultitenantCrequestMiddleware',
]

# Enables LDAP-backed authentication.
AUTHENTICATION_BACKENDS = (
    'core.backends.OurLDAPBackend',
    'core.backends.MultitenantModelBackend',
)

# Multitenant will be running on an indeterminate number of hosts, so all need to be allowed.
ALLOWED_HOSTS = ['*']

ROOT_URLCONF = 'base_project.urls'
WSGI_APPLICATION = 'base_project.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            # Normally the template debug setting shadows the global DEBUG setting. But we need to
            # set debug to False here or the FlexPage editor will load extremely slowly. You may
            # need to change this setting back to True if your templates are throwing errors.
            'debug': False,
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Static and media file handling.
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]
# noinspection PyUnresolvedReferences
STATIC_ROOT = '/static'
STATIC_URL = '/static/'
# noinspection PyUnresolvedReferences
MEDIA_ROOT = '/media'
MEDIA_URL = '/media/'

SECRET_KEY = getenv('SECRET_KEY')

# If you decide to use Memcached for your CACHES setting below, uncomment this line to tell Django to use cached
# sessions. If you don't use Memcached, though, Django will default to database-backed sessions, which need to be
# manually cleared out on a regular basis (see etc/dev/cron/daily/sessions.sh), and cause a DB hit on every request.
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
# Don't use persistent sessions, since that could lead to a sensitive information leak.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Use two-hour session cookies, so that browsers configured to ignore the above setting (Chrome and Firefox... grumble)
# still only get cookies with a short lifespan. The two-hour session timer starts as of the user's last request.
SESSION_COOKIE_AGE = 60 * 120

# Tell Django that it's running behind a proxy.
USE_X_FORWARDED_HOST = True
# This makes request.is_secure() return True when Apache has set the MULTITENANT-PROTOCOL header to 'https'.
SECURE_PROXY_SSL_HEADER = ('HTTP_MULTITENANT_PROTOCOL', 'https')

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

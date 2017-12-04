#################################################################
# Development Config
#################################################################
from djunk.utils import install_if_available, getenv
from .django import PROJECT_DIR, INSTALLED_APPS, TEMPLATES, MIDDLEWARE
from .logging import LOGGING
from .wagtail import WAGTAILSEARCH_BACKENDS

if getenv('DEVELOPMENT', False):
    # Useful info for syling custom admin pages. Not helpful to site users, though. Just developers.
    # NOTE: The static resources for this app will not be collected during docker image creation, because DEVELOPMENT
    # isn't true at that time. To get styleguide.css into place, run collectstatic manually in your dev container.
    INSTALLED_APPS.append('wagtail.contrib.wagtailstyleguide')
    # Don't send real emails during developmnent. Just print them to the console.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    # Don't validate passwords during development. Our rules make for hard-to-remember passwords.
    AUTH_PASSWORD_VALIDATORS = []
    # Don't use Sentry during development.
    INSTALLED_APPS.remove('raven.contrib.django.raven_compat')

    SERVER_EMAIL = DEFAULT_FROM_ADDRESS = WAGTAILADMIN_NOTIFICATION_FROM_EMAIL = 'oursites+dev@oursites.com'
    EMAIL_SUBJECT_PREFIX = '[oursites-dev] '

    # Django uses cached template loading by default, so we need to disable that during development or you won't
    # see any of the edits you make to templates. However, with template caching disabled, FlexPage forms load
    # extremely slowly. If you are actively using the FlexPage editor and can't stand 45+ second load times,
    # comment out the two TEMPLATES settings below.
    # NOTE: We have to set APP_DIRS=False because Django won't let us use 'APP_DIRS' and 'loaders' together.
    TEMPLATES[0]['APP_DIRS'] = False
    TEMPLATES[0]['OPTIONS']['loaders'] = [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader'
    ]

# Silence the "URL namespace 'wagtailusers_groups' isn't unique'" system check. We don't care about it because we have
# to override some of Wagtail's URLs in a way that triggers this check.
SILENCED_SYSTEM_CHECKS = ['urls.W005']

if getenv('TESTING', False):
    DEBUG = False

    # Use the much faster sqllite3 database during tests.
    # noinspection PyUnresolvedReferences
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': 'simple_test_db',
        },
    }

    # Don't log anything below Warnings during tests, since they'll get printed to stdout, polluting the test output.
    # We do want the warns/errors, even though some of them (e.g. Permission Denied) will pollute the output, because
    # otherwise we'll never learn about any *unexecpted* errors that don't crash the test (this happens with
    # elasticsearch sometimes).
    LOGGING['root']['level'] = 'WARN'

    # Don't polute the dev search index with test search content.
    WAGTAILSEARCH_BACKENDS['default']['INDEX'] = 'test'

    # Don't use Sentry during testing.
    if 'raven.contrib.django.raven_compat' in INSTALLED_APPS:
        INSTALLED_APPS.remove('raven.contrib.django.raven_compat')

    # Use a test runner that switches our DEFAULT_FILE_STORAGE setting from S3 to a temp folder on the local filesystem.
    TEST_RUNNER = 'base_project.test_runner.LocalStorageDiscoverRunner'

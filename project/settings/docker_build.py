# This file exists to allow collectstatic to run during the docker build process. We can't set environment variables
# in the normal way during that process, so we set them here before importing settings.py
import os

# These are the env vars that get retrieved with getenv(). They must be set to avoid raising UnsetEnvironmentVariable.
os.environ['DB_NAME'] = 'fake'
os.environ['DB_USER'] = 'fake'
os.environ['DB_PASSWORD'] = 'fake'
os.environ['DB_HOST'] = 'fake'
os.environ['DB_PORT'] = 'fake'
os.environ['CACHE'] = 'fake'
os.environ['AWS_STORAGE_BUCKET_NAME'] = 'fake'
os.environ['LDAP_URL'] = 'fake'
os.environ['LDAP_USER'] = 'fake'
os.environ['LDAP_PASSWORD'] = 'fake'
os.environ['LDAP_BASE_PEOPLE_DN'] = 'fake'
os.environ['WAGTAIL_ELASTICSEARCH_URL'] = 'fake'
os.environ['SERVER_DOMAIN'] = 'fake'
os.environ['SENTRY_DSN'] = 'https://fake:fake@sentry.io/fake'
os.environ['SECRET_KEY'] = 'dockerdefaultkey'

from .settings import *

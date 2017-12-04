#################################################################
# Cache Config
#################################################################
from djunk.utils import getenv

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://{}:6379'.format(getenv('CACHE')),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient'
        },
        'KEY_PREFIX': 'oursites',
    }
}

# Config for django-cacheops.
CACHEOPS_ENABLED = True
CACHEOPS_REDIS = 'redis://{}:6379/2'.format(getenv('CACHE'))
CACHEOPS = {
    'auth.user': {'ops': 'get', 'timeout': 60*15},
    # Automatically cache all gets and queryset fetches to other django.contrib.auth models for an hour
    'auth.*': {'ops': ('fetch', 'get'), 'timeout': 60*60},
    # Cache all queries to Permission
    # 'all' is just an alias for {'get', 'fetch', 'count', 'aggregate', 'exists'}
    'auth.permission': {'ops': 'all', 'timeout': 60*60},
    '*.*': {'timeout': 60*60},
}

# Disable all caching if the optional DISABLE_CACHE env var is True.
if getenv('DISABLE_CACHE', False):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
    CACHEOPS_ENABLED = False

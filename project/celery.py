from __future__ import absolute_import, unicode_literals
import os

from celery import Celery
import redis

from functools import wraps

from core.logging import logger

# Much like in manage.py, this sets the default Django settings module for the 'celery' commandline program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'multitenant.settings.settings')

app = Celery('multitenant')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


def with_lock(f):
    """
    Acquire a distributed lock in redis before running the Celery task.  If we
    can't acquire the lock, log that we couldn't and end the task.

    For logging purposes, we're assuming that every task is a Django manage.py
    command, that ``f`` is always ``django.core.management.call_command`` and
    that ``args[0]`` to ``call_command`` is the name of the command.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        lock_name = kwargs.pop('lock_name', os.environ.get('SERVER_DOMAIN', 'oursites.com')) + f.__name__
        timeout = kwargs.pop('timeout', 60 * 5)
        have_lock = False

        client = redis.Redis(
            host=os.environ.get('CACHE'),
            port=6379,
            db=2
        )
        lock = client.lock(lock_name, timeout=timeout)

        try:
            have_lock = lock.acquire(blocking=False)
            if have_lock:
                f(*args, **kwargs)
            else:
                logger.info('celery.task.lock.already_locked', task=f.__name__)
        finally:
            if have_lock:
                lock.release()
    return wrapper

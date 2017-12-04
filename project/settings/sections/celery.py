# This filename is captialized to avoid import issues with the celery library.
#################################################################
# Celery Config
#################################################################
from __future__ import absolute_import
import structlog
from celery.schedules import crontab
from celery.signals import after_setup_logger
from djunk.utils import getenv
from djunk.logging_handlers import ConsoleRenderer
from multitenant.settings.sections.logging import pre_chain

# When we're in the cloud (so that logstash can correctly group all the
# exception lines into one message), we modify the syslog formatter class.
# We'll know we're in the cloud beause deployfish will inject the
# DEPLOYFISH_SERVICE_NAME environment variable into our task configuraiton
# environment
newlines = getenv('DEPLOYFISH_SERVICE_NAME', None) is None
colors = getenv('COLORED_LOGGING', False)


# Like in logging.py, use struclog to handle our Celery log messages so we can add context to
# each message in a sane way.
@after_setup_logger.connect()
def logger_setup_handler(logger, **kwargs):
    for handler in logger.handlers:
        my_formatter = structlog.stdlib.ProcessorFormatter(
            ConsoleRenderer(colors=colors, repr_native_str=True, newlines=newlines),
            fmt='SYSLOG %(message)s',
            foreign_pre_chain=pre_chain
        )
        handler.setFormatter(my_formatter)

# Only universal tasks should be defined here. The rest got in the site_type settings blocks in settings.py.
CELERY_BEAT_SCHEDULE = {
    'publish-scheduled-pages': {
        # Runs Wagtail's scheduled publisher once every 5 minutes, ensuring that Pages scheduled to be published in the
        # future will go live in a timely manner.
        'task': 'core.tasks.publish_scheduled_pages',
        'schedule': crontab(minute='*/5'),
        'args': []
    },
    'rebuild-search-index': {
        # Runs Wagtail's search index rebuilder hourly.
        'task': 'core.tasks.rebuild_search_index',
        'schedule': crontab(minute=0),
        'args': []
    },
}
CELERY_TIMEZONE = 'America/Los_Angeles'
# These settings disable the pickle serializer, for security reasons.
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_RESULT_BACKEND = 'redis://{}:6379/0'.format(getenv('CACHE'))
CELERY_BROKER_URL = 'redis://{}:6379/0'.format(getenv('CACHE'))

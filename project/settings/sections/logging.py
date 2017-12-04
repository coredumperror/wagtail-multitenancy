#################################################################
# Logging Config.
#################################################################
import structlog
from core.logging import request_context_logging_processor, censor_password_processor
from djunk.logging_handlers import ConsoleRenderer
from djunk.utils import getenv

# Use structlog to ease the difficulty of adding context to log messages
# See https://structlog.readthedocs.io/en/stable/index.html
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt='iso'),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        request_context_logging_processor,
        censor_password_processor,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

timestamper = structlog.processors.TimeStamper(fmt='iso')
pre_chain = [
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    timestamper,
]

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'plain'
        },
        'null': {
            'level': 'DEBUG',
            'class': 'logging.NullHandler',
        },
    },
    'loggers': {
        'celery': {
            # Set up the celery logger to print to stdout.
            'handlers': ['console'],
            'level': 'INFO',
        },
        'elasticsearch': {
            # Elasticsearch is super chatty.  We don't need to know so much about indexing individual things.
            'handlers': ['console'],
            'level': 'ERROR',
        },
        'django.security.DisallowedHost': {
            # Don't log attempts to access the site with a spoofed HTTP-HOST header. It massively clutters the logs,
            # and we really don't care about this error.
            'handlers': ['null'],
            'propagate': False,
        },
    },
    'root': {
        # Set up the root logger to print to stdout.
        'handlers': ['console'],
        'level': 'INFO',
    },
    'formatters': {
        'plain': {
            '()': structlog.stdlib.ProcessorFormatter,
            'processor': ConsoleRenderer(colors=getenv('COLORED_LOGGING', False), repr_native_str=False, newlines=True),
            'foreign_pre_chain': pre_chain,
            'format': 'SYSLOG %(message)s'
        }
    },
}

RAVEN_CONFIG = {
    'dsn': getenv('SENTRY_DSN', None)
}

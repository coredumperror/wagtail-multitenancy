# Import the app-specific settings from their individual files in app_settings.
from .sections.auth import *
from .sections.aws import *
from .sections.cache import *
from .sections.celery import *
from .sections.database import *
from .sections.django import *
from .sections.i18n import *
from .sections.logging import *
from .sections.multitenant import *
from .sections.suit import *
from .sections.wagtail import *
# Development config has to go last because it overrides several settings from other files.
from .sections.development import *

PROJECT_NAME = 'multitenant'

##########################################################################
# Various Other Third Party App Configs That Don't Deserve Their Own Files
##########################################################################
# Set up django-js-reverse.
JS_REVERSE_JS_VAR_NAME = 'URLs'

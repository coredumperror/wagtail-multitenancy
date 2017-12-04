"""
WSGI config for multitenant project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application
from djunk.utils import getenv

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'multitenant.settings.settings')

# If the environment is configured to enable remote debugging, attach to the configured remote debug server.
# If REMOTE_DEBUG_ENABLED set to True, REMOTE_DEBUG_HOST and REMOTE_DEBUG_PORT are required.
if getenv('REMOTE_DEBUG_ENABLED', False):
    # We keep this import inside the REMOTE_DEBUG_ENABLED check because simply doing the import slows down the process,
    # even if we don't call settrace().
    print("Debugging Enabled")
    import pydevd
    # Attach to a Remote Debugger session running in PyCharm or PyDev on the configured host and port.
    # NOTE: If no remote debug server is running, this call will hang indefinitely. Be aware of this!
    pydevd.settrace(
        host=getenv('REMOTE_DEBUG_HOST'),
        port=getenv('REMOTE_DEBUG_PORT'),
        suspend=False
    )

application = get_wsgi_application()

#################################################################
# Multitenant Config
#################################################################
from djunk.utils import getenv

# Defines the base domain for all Sites on this server. e.g. 'oursites.com'
SERVER_DOMAIN = getenv('SERVER_DOMAIN')

# Specify the prefixes for paths that NEED to end in slash, so that SlashMiddleware can redirect us to them from their
# slashless versions. e.g. going to /admin/login will redirect to /admin/login/
SLASHED_PATHS = ['/admin', '/django-admin']

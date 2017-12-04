import ldap
from djunk.utils import getenv
from django_auth_ldap.config import LDAPSearch

#################################################################
# django-auth-ldap Config
#################################################################
AUTH_LDAP_SERVER_URI = getenv('LDAP_URL')
AUTH_LDAP_BIND_DN = getenv('LDAP_USER')
AUTH_LDAP_BIND_PASSWORD = getenv('LDAP_PASSWORD')
AUTH_LDAP_START_TLS = True
AUTH_LDAP_USER_SEARCH = LDAPSearch(getenv('LDAP_BASE_PEOPLE_DN'), ldap.SCOPE_SUBTREE, "(uid=%(user)s)")

#################################################################
# django-auth password validator config
#################################################################
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
        'OPTIONS': {
            'user_attributes': ['username', 'first_name', 'last_name', 'email']
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 10,
        }
    },
    {
        'NAME': 'core.validators.LocalUserPasswordValidator',
    },
    {
        'NAME': 'core.validators.MaximumLengthValidator',
        'OPTIONS': {
            'max_length': 20,
        }
    },
]

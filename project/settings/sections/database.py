#################################################################
# Database Config
#################################################################
from djunk.utils import getenv

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': getenv('DB_NAME'),
        'HOST': getenv('DB_HOST'),
        'PORT': getenv('DB_PORT'),
        'USER': getenv('DB_USER'),
        'PASSWORD': getenv('DB_PASSWORD'),
        'OPTIONS': {
            'sql_mode': 'ANSI,STRICT_TRANS_TABLES',
        }
    },
}

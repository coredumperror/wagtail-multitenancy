from djunk.utils import getenv

#################################################################
# django-storages Config
#################################################################
# Use our subclass of S3Boto3Storage.
AWS_S3_REGION_NAME = getenv('AWS_DEFAULT_REGION', 'us-west-2')
AWS_STORAGE_BUCKET_NAME = getenv('AWS_STORAGE_BUCKET_NAME')
AWS_S3_FILE_OVERWRITE = False
# These credentials aren't used in test/prod; the IAM role is used instead. So they're allowed to not be set.
AWS_ACCESS_KEY_ID = getenv('AWS_ACCESS_KEY_ID', None)
AWS_SECRET_ACCESS_KEY = getenv('AWS_SECRET_ACCESS_KEY', None)
AWS_DEFAULT_ACL = 'public-read'

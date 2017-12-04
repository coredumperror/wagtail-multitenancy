import boto3
from django.conf import settings
from django.core.management import call_command
from celery import shared_task

from base_project.celery import with_lock


@shared_task
@with_lock
def publish_scheduled_pages():
    call_command('publish_scheduled_pages')


@shared_task
@with_lock
def rebuild_search_index():
    call_command('update_index')


@shared_task
def rename_files_for_hostname_change(old_hostname, new_hostname):
    """
    Renames all the files in the S3 bucket that match old_hostname/*, changing their paths to new_hostname/*.

    NOTE: Unlike the other tasks in this file, this function is not called via CeleryBeat. Instead, calling it requires
    a special method, as laid out in the docs: http://docs.celeryproject.org/en/latest/userguide/calling.html#example
    One must call this function by calling the apply_async() method upon it, like so:
    from core.tasks import rename_files_for_hostname_change

    rename_files_for_hostname_change.apply_async(args=['old.hostname.oursites.com', 'new.hostname.oursites.com'])
    """
    client = boto3.client('s3', region_name=settings.AWS_S3_REGION_NAME)
    # Create an iterator over the list_objects API. This lets us automatically deal with pagination, in case there are
    # more than 1000 objects prefixed with old_hostname in the bucket.
    page_iterator = client.get_paginator('list_objects').paginate(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=old_hostname
    )

    # Loop through all the files in the bucket that belong to the Site which was at old_hostname.
    keys_to_delete = []
    for page in page_iterator:
        for obj in page['Contents']:
            old_key = obj['Key']
            # Replace the first occurence of old_hostname in the key with new_hostname.
            new_key = old_key.replace(old_hostname, new_hostname, 1)

            # Since we need to copy/delete, keep track of all the old keys, so we can delete them when we're done.
            keys_to_delete.append(old_key)

            # All our files get the 'public-read' ACL except for documents, which need to be given 'private'.
            # Unfortuantely, copy_object() doesn't just copy the original file's ACL, so we need to do this manually.
            acl = 'public-read'
            if new_key.startswith('{}/documents/'.format(new_hostname)):
                acl = 'private'

            # Copy the file from old_key into new_key.
            client.copy_object(
                CopySource={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': old_key},
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=new_key,
                ACL=acl
            )

    # Loop through keys_to_delete, building a Delete command of no more than 1000 keys at a time for delete_objects().
    range_start = 0
    MAX_KEYS = 1000
    results = []
    while True:
        delete_cmd = {
            'Objects': [
                {'Key': key} for key in keys_to_delete[range_start:range_start+MAX_KEYS]
            ]
        }
        results.append(
            client.delete_objects(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Delete=delete_cmd)
        )

        range_start += MAX_KEYS
        if range_start > len(keys_to_delete):
            break

    # TODO: Do something with 'results'...?

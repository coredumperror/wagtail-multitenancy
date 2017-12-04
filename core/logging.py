from __future__ import absolute_import, unicode_literals

import structlog
from six import string_types
from djunk.utils import get_client_ip
from djunk.middleware import get_current_request

from core.modeldict import model_to_dict

logger = structlog.get_logger('oursites')


def request_context_logging_processor(_, __, event_dict):
    """
    Adds extra runtime event info to our log messages based on the current request.

        ``username``: (string) the username of the logged in user, if user is logged in.
        ``site``: (string) the hostname of the current Site. Logs as 'celery/manage.py' when there's no current request.
        ``remote_ip``: the X-Forwarded-For header.
        ``superuser``: True if the current User is a superuser

    Does not overwrite any event info that's already been set in the logging call.
    """
    request = get_current_request()
    if request is not None:
        try:
            client_ip = get_client_ip(request)
        except AttributeError:
            # Sometimes there will be a current request, but it's not a real request (during tests). If we can't get
            # the real client ip, just use a placeholder.
            client_ip = 'fake IP'
        event_dict.setdefault('remote_ip', client_ip)
        event_dict.setdefault('site', request.site.hostname)
        # request.user.username is the empty string if the "current user" is annonymous.
        event_dict.setdefault('username', request.user.username or 'AnonymousUser')
        event_dict.setdefault('superuser', request.user.is_superuser)
    else:
        # We're in a celery app or a manage.py command, which means there is no remote_ip, logged-in user, or
        # "current site" so we log the "site" as 'celery/manage.py'.
        event_dict.setdefault('site', 'celery/manage.py')
    return event_dict


def censor_password_processor(_, __, event_dict):
    """
    Automatically censors any logging context key called "password", "password1", or "password2".
    """
    for password_key_name in ('password', 'password1', 'password2'):
        if password_key_name in event_dict:
            event_dict[password_key_name] = '*CENSORED*'
    return event_dict


def get_logger():
    """
    Deprecated. Rather than calling get_logger(), one should use "from core.logging import logger".
    """
    return logger


def log_compat(obj):
    """
    Convert the given object to a string that's compatible with the logger output.
    """
    # If obj isn't already a string, convert it to one.
    if not isinstance(obj, string_types):
        obj = repr(obj)
    return obj


def log_model_changes(original, new):
    """
    Logs the changes made from the original instance to new instance.
    """
    original_dict = model_to_dict(original, exclude_passwords=True)
    new_dict = model_to_dict(new, exclude_passwords=True)

    changes = {}
    for field_name, original_value in original_dict.items():
        new_value = new_dict.get(field_name)
        try:
            if original_value != new_value:
                # Must import locally to avoid circular import.
                from wagtail.wagtailcore.blocks import StreamValue
                if isinstance(new_value, StreamValue):
                    # We do this to avoid rendering the StreamValue, which could lead to unexpected results if this
                    # change is logged outside of the normal request cycle (like during a migration).
                    changes[field_name] = '"A StreamValue" -> "A different StreamValue"'
                else:
                    changes[field_name] = '"{}" -> "{}"'.format(original_value, new_value)
        except TypeError:
            # Some fields (e.g. dates) can potentially trigger this kind of error when being compared. If that happens,
            # there's not much we can do about it, so we just skip that field.
            pass
    if changes:
        if original._meta.label == 'auth.User':
            if 'last_login' in changes and len(changes) == 1:
                # Don't log changes that are only to the "last_login" field on the auth.User model.
                # That field gets changed every time the user logs in, and we already log logins.
                return
            if 'password' in changes:
                # Don't log the new password hash
                changes['password'] = "__NEW_PASSWORD__"
        # Don't let the "model" keyword that we set manually on info() conflict with the "changes" dict, which can
        # happen when renaming a model in a migration.
        if 'model' in changes:
            changes['other_model'] = changes.pop('model')
        logger.info('model.update', model=original._meta.label, **changes)


def log_model_m2m_changes(instance, action, model, pk_set):
    """
    Logs the changes made to an object's many-to-many fields.
    """
    # The post_add and post_remove signals get sent even if no changes are actually made by their respective actions
    # (e.g. when add()'ing an object that's already in the m2m relationship).
    # Since there are no changes, there's nothing to log.
    if not pk_set:
        return

    if action == "post_remove":
        removed_objects = model.objects.filter(pk__in=pk_set)
        logger.info(
            'model.m2m.delete',
            model=instance._meta.label,
            objects=", ".join(log_compat(obj) for obj in removed_objects),
            instance=log_compat(instance)
        )
    elif action == "post_add":
        added_objects = model.objects.filter(pk__in=pk_set)
        logger.info(
            'model.m2m.add',
            model=instance._meta.label,
            objects=", ".join(log_compat(obj) for obj in added_objects),
            instance=log_compat(instance)
        )


def log_new_model(instance):
    """
    Logs the field values set on a newly-saved model instance.
    """
    kwargs = model_to_dict(instance, exclude_passwords=True)
    if 'model' not in kwargs:
        kwargs['model'] = instance._meta.label
    if 'event' in kwargs:
        # the first argument to logger.info here is technically a kwarg called
        # 'event', so if kwargs also has a key in it called 'event', our
        # logger.info call will raise an exception about duplicate keyword args
        kwargs['event_obj'] = kwargs['event']
        del kwargs['event']
    logger.info('model.create', instance=log_compat(instance), **kwargs)


def log_model_deletion(instance):
    """
    Logs the deletion of this model instance.
    """
    kwargs = model_to_dict(instance, exclude_passwords=True)
    if 'event' in kwargs:
        # the first argument to logger.info here is technically a kwarg called
        # 'event', so if kwargs also has a key in it called 'event', our
        # logger.info call will raise an exception about duplicate keyword args
        kwargs['event_obj'] = kwargs['event']
        del kwargs['event']
    logger.info('model.delete', model=instance._meta.label, instance=log_compat(instance), **kwargs)

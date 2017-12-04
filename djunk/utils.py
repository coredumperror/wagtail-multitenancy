import os
from ast import literal_eval
from django.db.models.constants import LOOKUP_SEP

CRASH_DEFAULT = 'crash-if-env-var-is-not-set'


class UnsetEnvironmentVariable(NameError):
    pass


def getenv(var_name, default=CRASH_DEFAULT):
    """
    Returns the environment variable with the specified name. If that env var is not set, and the 'default' argument
    has not been specified, this function raises UnsetEnvironmentVariable.

    This function automatically converts 'False' and 'True' to booleans and integers values to ints.
    """
    value = os.getenv(var_name, default)
    if value == CRASH_DEFAULT:
        raise UnsetEnvironmentVariable(
            "The '{}' environment variable is not set, and no default was provided.".format(var_name)
        )

    # Convert the string value of the env var to a literal. e.g. 'False' to False, '45' to 45, etc.
    try:
        return literal_eval(value)
    except (ValueError, SyntaxError):
        # If literal_eval() throws ValueError, it could not convert value to a python literal. If that happens, we
        # just return value itself, because it might be something like 'test' or None, which are valid values.
        return value

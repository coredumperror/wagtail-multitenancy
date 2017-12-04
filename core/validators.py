import re
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError


def validate_phone_number(value):
    return RegexValidator(r'^\d{3}-\d{3}-\d{4}$', 'Enter a valid telephone number: xxx-yyy-zzzz')


class LocalUserPasswordValidator(object):
    def __init__(self):
        self.error_message = (
            "Your password must fulfill at least three of the following criteria:\n" +
                "    * contain two or more uppercase letters\n" +
                "    * contain two or more lowercase letters\n" +
                "    * contain two or more digits\n" +
                "    * contain two or more symbols\n"
        )

    def validate(self, password, user=None):
        count = 0
        patterns = [
            "[a-z].*[a-z]",  # at least 2 lowercase letters
            "[A-Z].*[A-Z]",  # at least 2 uppercase letters
            "[0-9].*[0-9]",  # at least 2 numbers
            "[\W_].*[\W_]",  # at least 2 characters not in the above groups. Note that
                             # we had to add "_" in addition to \W, because "_" is not in \W
        ]
        for pattern in patterns:
            pattern_re = re.compile(pattern)
            if pattern_re.search(password):
                count = count + 1

        if count < 3:
            raise ValidationError(self.error_message)

    def get_help_text(self):
        return self.error_message


class MaximumLengthValidator(object):
    """
    Validates that a password is no longer than a specified maximum length.
    """

    def __init__(self, max_length=20):
        self.max_length = max_length
        self.error_message = "This password is too long. It must contain no more than {} characters.".format(max_length)

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(self.error_message, code='password_too_long', params={'max_length': self.max_length})

    def get_help_text(self):
        return self.error_message

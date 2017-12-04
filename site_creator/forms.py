from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from wagtail.wagtailadmin.widgets import AdminPageChooser
from wagtail.wagtailcore.models import Site, Page
from wagtail.wagtailsites.forms import SiteForm

from core.tasks import rename_files_for_hostname_change
from core.utils import get_alias_and_hostname_validators, update_db_for_hostname_change
from djunk.middleware import get_current_request
from site_creator.utils import create_site, generate_homepage_title


class SiteCreationForm(forms.ModelForm):
    """
    This form creates a new Site, along with all the things that a Site requires to function.
    """
    required_css_class = 'required'

    hostname = forms.CharField(
        label='Subdomain',
        max_length=50,
        help_text="The subdomain at which this Site will live. e.g. 'test1' puts it at test1.{}".format(
            settings.SERVER_DOMAIN
        )
    )
    site_name = forms.CharField(
        label='Site Name',
        help_text="The name of the Site, which will appear in various places on the Site's pages."
    )

    def clean_hostname(self):
        """
        The hostname field is presented as the "Subdomain" field. But we need to validate the full hostname that will be
        built from the subdomain and the SERVER_DOMAIN setting. Then we return the full hostname, as if the user
        had input that value in the form.
        """
        subdomain = self.cleaned_data['hostname']
        if '.' in subdomain:
            raise ValidationError('Plase provide an undotted string containing only the subdomain for this Site.')
        else:
            hostname = '{}.{}'.format(subdomain, settings.SERVER_DOMAIN)

        # Confirm that the full hostname is valid. This will throw a ValidationError if it isn't.
        for validator in get_alias_and_hostname_validators(site_creator=True):
            validator(hostname)

        # Return the full hostname, rather then the original subdomain string.
        return hostname

    def clean_site_name(self):
        """
        The Site Name has to be unique, because this new Site's homepage will be given a slug based on the Site Name.
        """
        site_name = self.cleaned_data['site_name']
        homepage_slug = slugify(generate_homepage_title(site_name))

        if Site.objects.filter(site_name=site_name).exists():
            raise ValidationError('Another site already exists with that name.')
        if Page.objects.filter(slug=homepage_slug).exists():
            raise ValidationError("A page already exists with the slug '{}'.".format(homepage_slug))

        return site_name

    class Meta:
        model = Site
        fields = ('hostname', 'site_name')

    def save(self, owner=None):
        return create_site(owner, self.cleaned_data)


class SiteEditForm(SiteForm):
    """
    This child of wagtailsites.forms.Siteform performs the necessary external changes when the hostname is changed.
    """

    def save(self, commit=True):
        instance = super().save(commit)
        if 'hostname' in self.changed_data:
            # The hostname has been changed, so we need to do a bunch of internal renames to account for that.
            old_hostname = self['hostname'].initial
            new_hostname = instance.hostname
            # Update the database to change all the places where the old hostname appears which wouldn't otherwise be
            # changed by this form.
            update_db_for_hostname_change(old_hostname, new_hostname)
            # Send an asynchronous task to Celery that renames the files in the S3 bucket that belong to this Site.
            rename_files_for_hostname_change.apply_async(args=[old_hostname, new_hostname])
            messages.success(
                get_current_request(),
                "{} has been moved from {} to {}. The process of renaming the files in S3 is underway, "
                "and may take a few minutes to complete.".format(instance.site_name, old_hostname, new_hostname)
            )
        return instance

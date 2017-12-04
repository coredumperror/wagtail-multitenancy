from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.tests.factories.user import UserFactory
from core.tests.factories.site import SiteFactory, TCMSSettingsFactory
from core.tests.utils import SecureClientMixin, MultitenantSiteTestingMixin


class FormIntegrationTest(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):
    # NOTE: We use 'wagtailsites:add' because we took over the wagtailsites ViewSet, which determines the name of
    # the view we want.

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserFactory(username='superuser', is_superuser=True)

    def test_form_display_on_GET(self):
        self.login(self.superuser.username)
        response = self.client.get(reverse('wagtailsites:add'), HTTP_HOST='localhost')

        self.assertContains(response, 'Create a New Site')

    def test_empty_fields(self):
        self.login(self.superuser.username)
        response = self.client.post(
            reverse('wagtailsites:add'),
            {'hostname': '', 'site_name': ''},
            HTTP_HOST='localhost'
        )

        self.assertFormError(response, 'form', 'hostname', 'This field is required.')
        self.assertFormError(response, 'form', 'site_name', 'This field is required.')

    def test_hostname_already_in_use_as_hostname(self):
        self.login(self.superuser.username)
        existing_site = SiteFactory(hostname='example.{}'.format(settings.SERVER_DOMAIN))

        response = self.client.post(
            reverse('wagtailsites:add'),
            {'hostname': existing_site.hostname.split('.')[0], 'site_name': 'a random name'},
            HTTP_HOST='localhost'
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'hostname',
            'This domain name is already in use by another Site.'
        )

    def test_hostname_already_in_use_as_alias(self):
        self.login(self.superuser.username)
        site = SiteFactory(settings=TCMSSettingsFactory.build(
            aliases=['alias.{}'.format(settings.SERVER_DOMAIN), 'alias2.{}'.format(settings.SERVER_DOMAIN)]
        ))

        form_values = {
            'hostname': site.settings.aliases.all()[0].domain.split('.')[0],
            'site_name': 'some other site name'
        }
        response = self.client.post(reverse('wagtailsites:add'), form_values, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'hostname', 'This domain name is already in use by another Site.')

        form_values['hostname'] = site.settings.aliases.all()[1].domain.split('.')[0]
        response = self.client.post(reverse('wagtailsites:add'), form_values, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'hostname', 'This domain name is already in use by another Site.')

    def test_hostname_is_dotted_string(self):
        self.login(self.superuser.username)

        form_values = {'hostname': 'illegal.domain.name', 'site_name': 'Bad Names'}
        response = self.client.post(reverse('wagtailsites:add'), form_values, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response, 'form', 'hostname',
            'Plase provide an undotted string containing only the subdomain for this Site.'
        )

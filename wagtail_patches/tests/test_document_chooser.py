from django.http.request import QueryDict
from testfixtures import Replacer
from ads_extras.testing.dummy import Dummy
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from wagtail.wagtailcore.models import Site
from wagtail.wagtaildocs.models import Document

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin, DummyFile
from ..monkey_patches import patched_document_chooser


class TestDocumentChooser(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

    @classmethod
    def setUpTestData(cls):
        cls.set_up_test_sites_and_users()
        cls.wagtail_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'wagtail.flint.oursites.com',
        })
        cls.test_factory = RequestFactory(**{
            'wsgi.url_scheme': 'https',
            'SERVER_NAME': 'test.flint.oursites.com',
        })
        call_command('update_index', stdout=DummyFile())

    def setUp(self):
        super(TestDocumentChooser, self).setUp()

        # The render_modal_workflow() function pre-renders its output, making it difficult to debug. Thus, we usually
        # dummy it out so that we can test the context variables that the patched_document_chooser function sets up.
        self.render_modal_workflow_dummy = Dummy()

    def get_context_variable_from_render_modal_dummy(self, var_name):
        return self.render_modal_workflow_dummy.calls[0]['args'][3][var_name]

    def test_routing(self):
        get_document_model_dummy = Dummy(default_return=Document)
        self.login('superuser')
        with Replacer() as r:
            # Dummy out the get_document_model() function within wagtail_patches.monkey_patches, so we can confirm that
            # that our version of the function is running at the correct URL.
            r.replace('wagtail_patches.monkey_patches.get_document_model', get_document_model_dummy)
            response = self.client.get(reverse('wagtaildocs:chooser'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(get_document_model_dummy.calls), 2)

    def test_wagtail_admins_see_only_wagtail_documents_page_1(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_document_chooser(request)
            docs = self.get_context_variable_from_render_modal_dummy('documents')
            # Confirm that there are exactly 10 "Wagtail Documents" in the listing, and that they are in reverse
            # creation order. This also proves that there are no "Test Documents" in the listing.
            self.assertEqual(len(docs), 10)
            for ndx, doc in enumerate(docs):
                self.assertFalse("Test" in doc.title)

    def test_wagtail_admins_see_only_wagtail_documents_page_2(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Request page 2 of the listing. This code path *does* return a response that can be tested against,
            # so we don't use the modal workflow dummy.
            request.GET = QueryDict('p=2')
            response = patched_document_chooser(request)
            docs = response.context_data['documents']
            # This time, there should be three remaining Wagtail Documents, and nothing else.
            self.assertEqual(len(docs), 3)
            for ndx, doc in enumerate(docs):
                self.assertEqual(doc.title, 'Wagtail Document {}'.format(3 - ndx))

    def test_only_permitted_collections_are_displayed(self):

        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_document_chooser(request)
            collections = self.get_context_variable_from_render_modal_dummy('collections')
            # Confirm that the colletion var is None, since the Wagtail Admins only have permissions on a single
            # Collection, so a selector is pointless.
            self.assertEqual(collections, None)

    def test_test_admins_see_only_test_documents_page_1(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_document_chooser(request)
            docs = self.get_context_variable_from_render_modal_dummy('documents')
            # Confirm that there are exactly 2 "Test Documents" in the listing, and that they are in reverse
            # creation order.
            self.assertEqual(len(docs), 2)
            for ndx, doc in enumerate(docs):
                self.assertEqual(doc.title, 'Test Document {}'.format(2 - ndx))

    def test_wagtail_admins_see_only_wagtail_documents_in_search_results(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Request page 2 of the listing. This code path *does* return a response that can be tested against,
            # Search for the word "GarbageQuery".
            request.GET = QueryDict('q=GarbageQuery')
            response = patched_document_chooser(request)
            docs = response.context_data['documents']
            # Wagtail users should see no results.
            self.assertEqual(len(docs), 0)

        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Request page 2 of the listing. This code path *does* return a response that can be tested against,
            # Search for the word "Test".
            request.GET = QueryDict('q=Test')
            response = patched_document_chooser(request)
            docs = response.context_data['documents']
            # Test users should see 2 results.
            self.assertEqual(len(docs), 2)
            titles = [d.title for d in docs]
            self.assertIn('Test Document 1', titles)
            self.assertIn('Test Document 2', titles)

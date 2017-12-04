from django.http.request import QueryDict
from testfixtures import Replacer
from ads_extras.testing.dummy import Dummy
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.http.response import HttpResponse
from django.test import TestCase
from django.test.client import RequestFactory
from wagtail.wagtailcore.models import Site

from core.tests.utils import MultitenantSiteTestingMixin, SecureClientMixin, DummyFile
from wagtail_patches.monkey_patches import patched_image_chooser


class TestImageChooser(SecureClientMixin, TestCase, MultitenantSiteTestingMixin):

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
        super(TestImageChooser, self).setUp()

        # The render_modal_workflow() function pre-renders its output, making it difficult to debug. Thus, we
        # must dummy it out so that we can test the context variables that the image_chooser function sets up.
        self.render_modal_workflow_dummy = Dummy(default_return=HttpResponse())

    def get_context_variable_from_render_modal_dummy(self, var_name):
        return self.render_modal_workflow_dummy.calls[0]['args'][3][var_name]

    def test_routing(self):
        self.login('superuser')
        get_current_request_dummy = Dummy(
            default_return=Dummy(
                site=Site.objects.get(hostname='wagtail.flint.oursites.com'),
                user=get_user_model().objects.get(username='superuser')
            )
        )

        with Replacer() as r:
            # Dummy out the render_modal_workflow() function, so we don't have to worry about rendering our test image
            # data to HTML. It won't work, due to convoluted problems that I couldn't solve.
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            response = self.client.get(reverse('wagtailimages:chooser'), HTTP_HOST=self.wagtail_site.hostname)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(self.render_modal_workflow_dummy.calls), 1)

    def test_wagtail_admins_see_only_wagtail_images_page_1(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))

        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_image_chooser(request)
            images = self.get_context_variable_from_render_modal_dummy('images')
            # Confirm that there are exactly 12 "Wagtail Images" in the listing, and that they are in reverse
            # creation order. This also proves that there are no "Test Images" in the listing.
            self.assertEqual(len(images), 12)
            for ndx, img in enumerate(images):
                self.assertEqual(img.title, 'Wagtail Image {}'.format(13 - ndx))

    def test_wagtail_admins_see_only_wagtail_images_page_2(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Request page 2 of the listing. This code path *does* return a response that can be tested against,
            # so we don't use the modal workflow dummy.
            request.GET = QueryDict('p=2')
            response = patched_image_chooser(request)
            images = response.context_data['images']
            # This time, there should be just the one remaining Wagtail Image, and nothing else. It's Image 1 because
            # the list is in reverse order.
            self.assertEqual(len(images), 1)
            for doc in images:
                self.assertEqual(doc.title, 'Wagtail Image 1')

    def test_only_permitted_collections_are_displayed(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')
        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))

        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_image_chooser(request)
            collections = self.get_context_variable_from_render_modal_dummy('collections')
            # Confirm that the colletion var is None
            self.assertEqual(collections, None)

            """
            # OBSOLETE because we don't display a collections selector at any point other than to superusers
            # Give Wagtail Admins permissions on the test.flint.oursites.com Collection, which will let them see
            # a Collection selector.
            GroupCollectionPermission.objects.create(
                group=self.wagtail_admins_group, collection=self.test_collection, permission=self.add_image_perm
            )
            GroupCollectionPermission.objects.create(
                group=self.wagtail_admins_group, collection=self.test_collection, permission=self.change_image_perm
            )
            self.render_modal_workflow_dummy.reset_dummy()
            patched_image_chooser(request)
            collections = self.get_context_variable_from_render_modal_dummy('collections')
            # Confirm that the collection context var is now a queryset containing both Collections.
            self.assertEqual(len(collections), 2)
            names = [c.name for c in collections]
            self.assertIn('wagtail.flint.oursites.com', names)
            self.assertIn('test.flint.oursites.com', names)

            """

    def test_test_admins_see_only_test_images_page_1(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')
        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))

        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_image_chooser(request)
            images = self.get_context_variable_from_render_modal_dummy('images')
            # Confirm that there are exactly 2 "Test Images" in the listing, and that they are in reverse
            # creation order.
            self.assertEqual(len(images), 2)
            for ndx, doc in enumerate(images):
                self.assertEqual(doc.title, 'Test Image {}'.format(2 - ndx))

    def test_wagtail_admins_see_only_wagtail_images_in_search_results(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Search for the word "Test".
            request.GET = QueryDict('q=Test')
            response = patched_image_chooser(request)
            images = response.context_data['images']
            # Wagtail users should see no results.
            self.assertEqual(len(images), 0)

        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Search for the word "Test".
            request.GET = QueryDict('q=Test')
            response = patched_image_chooser(request)
            images = response.context_data['images']
            # Test users should see 2 results.
            self.assertEqual(len(images), 2)
            titles = [d.title for d in images]
            self.assertIn('Test Image 1', titles)
            self.assertIn('Test Image 2', titles)

    def test_wagtail_admins_see_only_wagtail_images_in_tag_filter_results(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='wagtail_admin')
        request.site = Site.objects.get(hostname='wagtail.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Filter by tag "test" as wagtail_admin, which should return nothing.
            request.GET = QueryDict('tag=test')
            response = patched_image_chooser(request)
            images = response.context_data['images']
            # Wagtail users should see no results.
            self.assertEqual(len(images), 0)

        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            # Filter by tag "test" as test_admin, which should return all Test Images.
            request.GET = QueryDict('tag=test')
            response = patched_image_chooser(request)
            images = response.context_data['images']
            # Test users should see 2 results.
            self.assertEqual(len(images), 2)
            titles = [d.title for d in images]
            self.assertIn('Test Image 1', titles)
            self.assertIn('Test Image 2', titles)

    def test_image_tags_restricted_to_site_of_creation(self):
        request = self.wagtail_factory.get('/')
        request.user = get_user_model().objects.get(username='test_admin')
        request.site = Site.objects.get(hostname='test.flint.oursites.com')

        get_current_request_dummy = Dummy(default_return=Dummy(site=request.site, user=request.user))
        with Replacer() as r:
            r.replace('wagtail_patches.monkey_patches.render_modal_workflow', self.render_modal_workflow_dummy)
            r.replace('wagtail_patches.monkey_patches.get_current_request', get_current_request_dummy)
            patched_image_chooser(request)
            popular_tags = self.get_context_variable_from_render_modal_dummy('popular_tags')

            # popular_tags shoudl not contain the tag 'wagtail' because it doesn't exist
            # on this site
            self.assertTrue('wagtail' not in popular_tags.get().name)

            # Make sure that we did receive some tags, and not just an empty list
            self.assertTrue('test' in popular_tags.get().name)

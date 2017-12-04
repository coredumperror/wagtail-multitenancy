from django.test import TestCase
from with_asserts.mixin import AssertHTMLMixin

from core.tests.factories.user import UserFactory
from core.tests.utils import SecureClientMixin, MultitenantSiteTestingMixin


class TestRichTextEmbeds(SecureClientMixin, TestCase, AssertHTMLMixin, MultitenantSiteTestingMixin):
    fixtures = ['our_sites_test_pages.json']

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserFactory(username='superuser', is_superuser=True)

    def test_video_embed_in_rich_text(self):
        self.login(self.superuser.username)
        self.client.post(
            '/admin/pages/add/our_sites/flexpage/3/',
            {
                'next': [''],
                'title': ['Video Embed Test Page'],
                'body-count': ['1'],
                'body-0-deleted': [''],
                'body-0-order': ['0'],
                'body-0-type': ['FancyRichTextBlock'],
                'body-0-id': [''],
                'body-0-value-text': [
                    """
                    Hello World
                    <div class="embed-placeholder rich-text-deletable" contenteditable="false" data-embedtype="media" 
                            data-url="https://www.youtube.com/watch?v=VYnJH97mxiQ">
                        <a class="icon icon-cross text-replace delete-control">Delete</a>
                        <h3>Snail's House - Balloons</h3>
                        <p>URL: https://www.youtube.com/watch?v=VYnJH97mxiQ</p>
                            <p>Provider: YouTube</p>
                            <p>Author: Eternal</p>
                            <img src="https://i.ytimg.com/vi/mTJ8gJJq9B4/hqdefault.jpg" alt="Snail's House - Balloons">
                    </div>
                    """],
                'body-0-value-color-background_image': [''],
                'body-0-value-color-background_color': [''],
                'body-0-value-color-text_color': [''],
                'body-0-value-fixed_dimensions-height': ['200'],
                'body-0-value-fixed_dimensions-width': ['200'],
                'teaser_image': [''],
                'teaser_title': [''],
                'listing_title': [''],
                'slug': ['video-embed-test-page'],
                'nav_title': ['Video Embed Test Page'],
                'seo_title': [''],
                'show_title': ['on'],
                'show_in_menus': ['on'],
                'search_description': [''],
                'go_live_at': [''],
                'expire_at': [''],
                'action-publish': ['action-publish'],
            },
            HTTP_HOST='wagtail.flint.oursites.com'
        )

        response = self.client.get('/video-embed-test-page', HTTP_HOST='wagtail.flint.oursites.com')
        self.assertEqual(response.status_code, 200)

        with self.assertHTML(response.content, 'iframe') as tags:
            self.assertEqual(1, len(tags))

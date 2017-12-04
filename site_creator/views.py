from wagtail.wagtailadmin.views import generic
from wagtail.wagtailsites.views import SiteViewSet

from site_creator.forms import SiteCreationForm, SiteEditForm


class OurCreateView(generic.CreateView):
    page_title = 'Create a New Site'
    success_message = "Site '{0}' created."
    template_name = 'site_creator/create_site.html'


class OurSiteViewSet(SiteViewSet):
    add_view_class = OurCreateView

    @property
    def add_view(self):
        # We override this in order to separate the creation form from the edit form.
        return self.add_view_class.as_view(
            model=self.model,
            permission_policy=self.permission_policy,
            form_class=self.get_create_form_class(),
            index_url_name=self.get_url_name('index'),
            add_url_name=self.get_url_name('add'),
            edit_url_name=self.get_url_name('edit'),
            header_icon=self.icon,
        )

    @property
    def edit_view(self):
        # We override this in order to separate the creation form from the edit form.
        return self.edit_view_class.as_view(
            model=self.model,
            permission_policy=self.permission_policy,
            form_class=self.get_edit_form_class(for_update=True),
            index_url_name=self.get_url_name('index'),
            edit_url_name=self.get_url_name('edit'),
            delete_url_name=self.get_url_name('delete'),
            header_icon=self.icon,
        )

    def get_create_form_class(self, for_update=False):
        return SiteCreationForm

    def get_edit_form_class(self, for_update=False):
        return SiteEditForm

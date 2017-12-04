from django.apps import AppConfig


class WagtailPatchesConfig(AppConfig):
    name = 'wagtail_patches'
    verbose_name = 'Wagtail Patches'
    ready_is_done = False

    def ready(self):
        """
        This function runs as soon as the app is loaded. It executes our monkey patches to various parts of Wagtail
        that change it to support our architecture of fully separated tenants.
        """
        # As suggested by the Django docs, we need to make absolutely certain that this code runs only once.
        if not self.ready_is_done:
            # noinspection PyUnresolvedReferences
            from . import monkey_patches
            self.ready_is_done = True
        else:
            print("{}.ready() executed more than once! This method's code is skipped on subsequent runs.".format(
                self.__class__.__name__
            ))

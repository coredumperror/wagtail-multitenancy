import itertools
import ldap
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from wagtail.wagtailadmin.forms import LoginForm, BaseGroupCollectionMemberPermissionFormSet
from wagtail.wagtailcore.models import Collection
from wagtail.wagtailusers.forms import GroupForm

from core.logging import logger
from core.utils import search_ldap_for_user, user_is_member_of_site, populate_user_from_ldap


class DRYMixin(forms.Form):
    required_css_class = 'required'

    error_messages = {
        'duplicate_username': 'This site already has a user with that username.',
        'duplicate_username_local': 'That username is not available. Please choose another.',
        'duplicate_username_in_ldap': 'That username is already in use by someone. Please choose another.',
        'not_in_ldap': 'Please choose a username that matches an existing user in LDAP.',
        'ldap_lookup_failed': 'The LDAP lookup for this username failed. Please try again later.',
        'group_required': 'Users must be assigned to at least one group.',
        'group_required_superuser': 'This user must be assigned to at least one group, or be set as a Superuser.',
        'password_mismatch': "The two password fields didn't match.",
    }

    is_superuser = forms.BooleanField(
        label='Superuser',
        required=False,
        help_text='Superusers have full access to manage the entire server. Grant this status very sparingly.'
    )

    def configure_shared_fields(self):
        error_messages = self.fields['groups'].error_messages.copy()
        if not self.request.user.is_superuser:
            # Only superusers may grant superuser status to other users.
            self.fields.pop('is_superuser')

            # Site admins MUST assign at least one Group. Replace the messages with ones tailored to them.
            self.fields['groups'].required = True
            error_messages['required'] = self.error_messages['group_required']
            self.fields['groups'].help_text = "A user's groups determine their permissions within the site."

            # Non-superusers are allowed to see only the Groups that belong to the current Site.
            # This also reduces the displayed Group name from e.g. "hostname.oursites.com Admins" to just "Admins".
            self.fields['groups'].choices = (
                (g.id, g.name.replace(self.request.site.hostname, '').strip())
                for g
                in Group.objects.filter(name__startswith=self.request.site.hostname)
            )
            # Changing the queryset alone isn't sufficient to change the available choices on the form (the "choices"
            # setting was created during the field's init). But we have to change the queryset anyway because it's
            # what the validation code uses to determine if the specified inputs are valid choices.
            self.fields['groups'].queryset = Group.objects.filter(name__startswith=self.request.site.hostname)
        else:
            self.fields['groups'].help_text = """Normal users require a Group. However, superusers should NOT be
                in any Groups. Thus, this field is required only when the Superuser checkbox is unchecked."""
            # Replace the "Required" error message with one tailored to superusers.
            error_messages['required'] = self.error_messages['group_required_superuser']
        self.fields['groups'].error_messages = error_messages


class LDAPUserCreateForm(forms.ModelForm, DRYMixin):

    # TODO: Change the username field to an autocomplete that queries LDAP for potential usernames.
    username = forms.CharField(
        label='Username',
        required=True,
        help_text="Users log in with their LDAP credentials, so you must choose a username that exists in LDAP."
    )

    class Meta:
        model = get_user_model()
        # Our Users have their names and emails pulled from LDAP, so the form need only offer these fields:
        fields = [
            'username',
            'groups',
            'is_superuser',
        ]
        widgets = {
            'groups': forms.CheckboxSelectMultiple
        }

    def __init__(self, request, data=None):
        super(LDAPUserCreateForm, self).__init__(data)
        self.request = request
        self.configure_shared_fields()

    def clean_username(self):
        """
        Deny creation of a User if the username doesn't exist in LDAP.
        """
        username = self.cleaned_data['username']

        try:
            results = search_ldap_for_user(username)
        except ldap.LDAPError:
            logger.error('user.ldap.new.ldap_lookup_failed', target_user=username)
            raise forms.ValidationError(self.error_messages['ldap_lookup_failed'])
        else:
            if results:
                return username
            else:
                raise forms.ValidationError(self.error_messages['not_in_ldap'])

    def clean(self):
        super(LDAPUserCreateForm, self).clean()

        # The Groups field is not required when a Superuser is using the form. However, they must still assign the User
        # to a Group, and/or set the User as a Superuser.
        if (
            self.request.user.is_superuser and
            not self.cleaned_data.get('is_superuser') and
            not self.cleaned_data.get('groups')
        ):
            self.add_error('groups', forms.ValidationError(self.error_messages['group_required_superuser']))

    def validate_unique(self):
        """
        Normally, this function ensures that the form cannot create a user that
        already exists. But since we need to allow that, we override this
        function to ensure only that this username doesn't belong to a member of
        the current Site, or to a superuser.
        """
        try:
            user = get_user_model().objects.get(username=self.cleaned_data.get('username'))
        except get_user_model().DoesNotExist:
            pass
        else:
            if user_is_member_of_site(user, self.request.site) or user.is_superuser:
                self.add_error('username', forms.ValidationError(self.error_messages['duplicate_username']))

    def save(self, commit=True):
        """
        If a Django User with this username already exists, pull it from the DB and add the specified Groups to it,
        instead of creating a new User object.
        """
        user = super(LDAPUserCreateForm, self).save(commit=False)
        # Users can access django-admin iff they are a superuser.
        user.is_staff = user.is_superuser

        username = self.cleaned_data['username']
        groups = Group.objects.filter(pk__in=self.cleaned_data['groups']).all()
        logger_extras = {
            'target_user': username,
            'target_user_superuser': user.is_superuser,
            'groups': ", ".join(str(g) for g in groups)
        }
        try:
            existing_user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            existing_user = False
        else:
            user = existing_user
            for group in groups:
                user.groups.add(group)
        if existing_user:
            logger_extras['target_user_id'] = user.id

        populate_user_from_ldap(user)

        if commit:
            user.save()
            if not existing_user:
                # Set a random password for the user, otherwise they end up with
                # '' as their password.  If the LDAP user later gets removed
                # from LDAP (because they left, for instance), this
                # account reverts to being a local user and we don't want anyone
                # to be able to login as them.
                password = get_user_model().objects.make_random_password()
                user.set_password(password)

                # Only call save_m2m() if we're not updating an existing User. It'll try to overwrite the updated
                # user.groups list, AND it'll crash for some reason I haven't figured out.
                self.save_m2m()
                logger.info('user.ldap.create', **logger_extras)
            else:
                logger.info('user.ldap.update', **logger_extras)
        return user


class LocalUserCreateForm(forms.ModelForm, DRYMixin):

    username = forms.CharField(label='Username', required=True)
    email = forms.EmailField(required=True, label='Email')
    first_name = forms.CharField(required=True, label='First Name')
    last_name = forms.CharField(required=True, label='Last Name')
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password (confirm)', widget=forms.PasswordInput)
    is_superuser = forms.BooleanField(
        label='Administrator',
        required=False,
        help_text='Administrators have full access to manage any object or setting.'
    )

    class Meta:
        model = get_user_model()
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'password1',
            'password2',
            'groups',
            'is_superuser',
        ]
        widgets = {
            'groups': forms.CheckboxSelectMultiple
        }

    def __init__(self, request, data=None):
        super(LocalUserCreateForm, self).__init__(data)
        self.request = request
        self.configure_shared_fields()

    def clean(self):
        super(LocalUserCreateForm, self).clean()

        # The Groups field is not required when a Superuser is using the form. However, they must still either assign
        # the User to a Group or set the User as a Superuser.
        if (
            self.request.user.is_superuser and
            not self.cleaned_data.get('is_superuser') and
            not self.cleaned_data.get('groups')
        ):
            self.add_error('groups', forms.ValidationError(self.error_messages['group_required_superuser']))

        # If you do the below in a LocalUserCreateForm.clean_username() method,
        # is_superuser might not be cleaned by the time we need to clean the
        # username.  Thus we do it here.
        if not self.cleaned_data.get('is_superuser', False):
            self.cleaned_data['username'] = self.request.site.hostname + "-" + self.cleaned_data.get('username')

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(self.error_messages['password_mismatch'])
        return password2

    def validate_unique(self):
        """
        By default, the form will complain if a user already exists with that
        username. But that message is confusing for Site admins who don't have a
        User with that username on their particular site. This function changes
        the error message so it's non-confusng, but also vague enough not to
        suggest that other Sites exist.
        """
        # Ensure our username is not taken in LDAP; we have to un-namespace it before doing the LDAP lookup.
        if self.cleaned_data.get('username').startswith(self.request.site.hostname + "-"):
            username = self.cleaned_data.get('username')[len(self.request.site.hostname)+1:]
            try:
                ldap_user = search_ldap_for_user(username)
            except ldap.LDAPError:
                # Not taken in LDAP
                logger.exception('usr.local.ldap-check.exception', target_user=username)
            if ldap_user:
                logger.info('usr.local.ldap.taken', target_user=username)
                self.add_error('username', forms.ValidationError(self.error_messages['duplicate_username_in_ldap']))
        try:
            get_user_model().objects.get(username=self.cleaned_data.get('username'))
        except get_user_model().DoesNotExist:
            pass
        else:
            self.add_error('username', forms.ValidationError(self.error_messages['duplicate_username_local']))

    def save(self, commit=True):
        user = super(LocalUserCreateForm, self).save(commit=False)
        # Users can access django-admin iff they are a superuser.
        user.is_staff = user.is_superuser
        user.set_password(self.cleaned_data['password1'])

        if commit:
            user.save()

            # List the quoted group names for logging.
            group_names = [str(g) for g in Group.objects.filter(pk__in=self.cleaned_data['groups']).all()]
            if user.is_superuser:
                group_names.append('Superusers')
            self.save_m2m()
            logger.info(
                'user.local.create',
                target_user=user.username, target_user_superuser=user.is_superuser, groups=", ".join(group_names)
            )
        return user


class LDAPUserEditForm(forms.ModelForm, DRYMixin):

    class Meta:
        model = get_user_model()
        fields = [
            'groups',
            'is_active',
            'is_superuser',
        ]
        widgets = {
            'groups': forms.CheckboxSelectMultiple
        }

    def __init__(self, request, instance, data=None):
        super(LDAPUserEditForm, self).__init__(data, instance=instance)

        self.request = request
        self.configure_shared_fields()
        if not request.user.is_superuser:
            del self.fields['is_active']
        else:
            self.fields['is_active'].help_text = (
                'To prevent this user from logging in, uncheck this box instead of deleting the account.'
            )

    def clean(self):
        super(LDAPUserEditForm, self).clean()

        # Superusers are allowed to be ungrouped.
        if self.cleaned_data.get('is_superuser'):
            if self.errors.get('groups') and self.errors['groups'][0] == self.error_messages['group_required']:
                del self.errors['groups']
                # The clean_groups() function removed self.cleaned_data['groups'] due to the error, but that will cause
                # the groups list to go unchanged upon save. So we need to set it to empty list.
                self.cleaned_data['groups'] = []

        # A superuser must assign a User to a Group, and/or set that User as a Superuser. If they don't do at least one,
        # throw an informative error.
        if (
            self.request.user.is_superuser and
            not self.cleaned_data.get('is_superuser') and not self.cleaned_data.get('groups')
        ):
            self.add_error('groups', forms.ValidationError(self.error_messages['group_required_superuser']))

    def save(self, commit=True):
        """
        In case the data in LDAP has changed, or it failed to populate on the previous create/edit, we override save()
        to re-populate this User's personal info from LDAP.
        """
        user = super(LDAPUserEditForm, self).save(commit=False)
        # Users can access django-admin iff they are a superuser.
        user.is_staff = user.is_superuser
        populate_user_from_ldap(user)
        if commit:
            user.save()
            self.save_m2m()
            if self.has_changed():
                logger_extras = {
                    'target_user': user.username,
                    'target_user_superuser': user.is_superuser,
                }
                for field_name in self.changed_data:
                    logger_extras[field_name] = self.cleaned_data[field_name]
                logger.info('user.ldap.update', **logger_extras)
        return user


class LocalUserEditForm(forms.ModelForm, DRYMixin):

    email = forms.EmailField(required=True, label='Email')
    first_name = forms.CharField(required=True, label='First Name')
    last_name = forms.CharField(required=True, label='Last Name')
    password1 = forms.CharField(
        label='Password',
        required=False,
        widget=forms.PasswordInput,
        help_text='Leave blank if not changing.'
    )
    password2 = forms.CharField(
        label='Password (confirm)',
        required=False,
        widget=forms.PasswordInput,
        help_text='Enter the same password as above, for verification.'
    )

    class Meta:
        model = get_user_model()
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'groups',
            'is_active',
            'is_superuser',
            'password1',
            'password2',
        ]
        widgets = {
            'groups': forms.CheckboxSelectMultiple
        }

    def __init__(self, request, instance, data=None):
        # Store the user's original username now, so we can accurately log this later if their username changes.
        self.original_username = instance.username
        super(LocalUserEditForm, self).__init__(data, instance=instance)

        self.request = request
        self.configure_shared_fields()
        self.fields['is_active'].help_text = (
            'To prevent this user from logging in, uncheck this box instead of deleting the account.'
        )
        # We're namespacing our local users by prefixing them with the hostname
        # for the current site, but we don't want to show that to the site admin
        # user, so we need to strip it off before displaying it in the form.
        if self.initial['username'].startswith(request.site.hostname + "-"):
            self.initial['username'] = self.initial['username'][len(request.site.hostname)+1:]

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 != password2:
            raise forms.ValidationError(self.error_messages['password_mismatch'])
        return password2

    def clean_username(self):
        """
        We're namespacing our local user usernames by prefixing them with the site hostname.

        We don't do that if we're creating a superuser because we don't want superusers bound
        to a particular site.
        """
        if not self.cleaned_data.get('is_superuser', False):
            username = self.request.site.hostname + "-" + self.cleaned_data['username']
        else:
            username = self.cleaned_data['username']
        return username

    def clean(self):
        super(LocalUserEditForm, self).clean()

        # Superusers are allowed to be ungrouped.
        if self.cleaned_data.get('is_superuser'):
            if self.errors.get('groups') and self.errors['groups'][0] == self.error_messages['group_required']:
                del self.errors['groups']
                # The clean_groups() function removed self.cleaned_data['groups'] due to the error, but that will cause
                # the groups list to go unchanged upon save. So we need to set it to empty list.
                self.cleaned_data['groups'] = []

        # A superuser must assign a User to a Group, and/or set that User as a Superuser. If they don't do at least one,
        # throw an informative error.
        if (
            self.request.user.is_superuser and
            not self.cleaned_data['is_superuser'] and
            not self.cleaned_data.get('groups')
        ):
            self.add_error('groups', forms.ValidationError(self.error_messages['group_required_superuser']))

    def save(self, commit=True):
        """
        In case the data in LDAP has changed, or it failed to populate on the previous create/edit, we override save()
        to re-populate this User's personal info from LDAP.
        """
        user = super(LocalUserEditForm, self).save(commit=False)
        # Users can access django-admin iff they are a superuser.
        user.is_staff = user.is_superuser

        if self.cleaned_data['password1']:
            user.set_password(self.cleaned_data['password1'])

        if commit:
            user.save()
            self.save_m2m()
            if self.has_changed():
                logger_extras = {
                    'target_user': user.username,
                    'target_user_superuser': user.is_superuser,
                }
                for field_name in self.changed_data:
                    logger_extras[field_name] = self.cleaned_data[field_name]
                logger.info('user.local.update', **logger_extras)
        return user


class LocalUserAdminResetPasswordForm(PasswordResetForm):
    # These two fields exist because we need a way to communicate the username to the save() function, and because
    # PasswordResetForm defines "email" and the form won't validate unless we send something for that field.
    # This is why wagtail_patches/users/admin_reset_password.html has the "username" and "email" hidden inputs.
    username = forms.CharField(label="username", max_length=254)
    email = forms.CharField(label="email", max_length=254)

    # noinspection PyMethodOverriding
    def save(self, request):
        user = get_object_or_404(get_user_model(), username=self.cleaned_data['username'])
        kwargs = {
            'uidb64': urlsafe_base64_encode(force_bytes(user.id)),
            'token': default_token_generator.make_token(user)
        }
        reset_password_path = reverse('wagtailadmin_password_reset_confirm', kwargs=kwargs)
        domain = request.site.hostname
        context = {
            'user': user,
            'reset_password_url': 'https://{}{}'.format(domain, reset_password_path),
            'domain': domain,
        }
        self.send_mail(
            'wagtail_patches/users/reset_password_email_subject.txt',
            'wagtail_patches/users/reset_password_email.txt',
            context,
            from_email=settings.SERVER_EMAIL,
            to_email=user.email
        )
        logger.info(
            'user.local.password_reset.admin',
            target_user=user.username, target_user_superuser=user.is_superuser, target_user_email=user.email
        )


class MultitenantLoginForm(LoginForm):
    """
    We subclass LoginForm so we can customize the error messages and prevent users form logging in to Sites where
    they're not allowed.
    """

    error_messages = {
        'invalid_login': "Unrecognized username and password. Please try again.",
        'inactive': "This account is inactive.",
    }

    def confirm_login_allowed(self, user):
        super(MultitenantLoginForm, self).confirm_login_allowed(user)

        # At this point, we know the user successfully authenticated and is otherwise allowed to login.
        # Now we need to also ensure the user is allowed to login to the current Site.
        if not user.is_superuser and not user_is_member_of_site(user, self.request.site):
            logger.warning('auth.login.user_not_member', username=user.username)
            raise forms.ValidationError(self.error_messages['invalid_login'], code='invalid_credentials')


class MultitenantGroupForm(GroupForm):
    """
    This is just GroupForm, but with the group's full name obfuscated from non-superusers.

    ..notes::

        We should probably be logging when users create groups through this form.
    """

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')

        # Don't show the hostname part of the Group's name to non-superusers.
        if not self.request.user.is_superuser:
            instance = kwargs.get('instance')
            if instance and instance.name:
                instance.name = instance.name.replace(self.request.site.hostname, '').strip()

        super(MultitenantGroupForm, self).__init__(*args, **kwargs)

        # Exclude from non-superusers the ability to alter Site wrangling permissions.
        if not self.request.user.is_superuser:
            self.fields['permissions'].queryset = self.registered_permissions.exclude(codename__endswith='site')

    def clean_name(self):
        """
        Deny creation of a Group if a Group with the given name already exists.
        This is non-trivial because Non-superusers don't see, or POST, the Group's actual name.
        """
        # Non-superusers have their chosen name automatically appended to the site's hostname.
        real_name = self.cleaned_data['name']
        if not self.request.user.is_superuser:
            real_name = '{} {}'.format(self.request.site.hostname, self.cleaned_data['name'])

        try:
            Group.objects.get(name=real_name)
        except Group.DoesNotExist:
            return real_name

        if self.instance and self.instance.pk and self.cleaned_data['name'] == self.instance.name:
            # This is an EDIT form, and the Group that the above code matched is THIS Group, so there's no problem.
            return real_name
        else:
            # We can't let this Group be created/edited with the name of another existing Group.
            raise forms.ValidationError(self.error_messages['duplicate_name'])


class MultitenantBaseGroupCollectionMemberPermissionFormSet(BaseGroupCollectionMemberPermissionFormSet):
    """
    This class exists just to let us pass the request into the form class as form_kwargs.
    """
    def __init__(self, data=None, files=None, instance=None, prefix=None, form_kwargs=None):
        if prefix is None:
            prefix = self.default_prefix

        if instance is None:
            instance = Group()

        self.instance = instance

        initial_data = []

        for collection, collection_permissions in itertools.groupby(
            instance.collection_permissions.filter(
                permission__in=self.permission_queryset,
            ).order_by('collection'),
            lambda cperm: cperm.collection
        ):
            initial_data.append({
                'collection': collection,
                'permissions': [cp.permission for cp in collection_permissions]
            })

        super(BaseGroupCollectionMemberPermissionFormSet, self).__init__(
            data, files, initial=initial_data, prefix=prefix, form_kwargs=form_kwargs
        )
        for form in self.forms:
            form.fields['DELETE'].widget = forms.HiddenInput()


def multitenant_collection_member_permission_formset_factory(
    model, permission_types, template, default_prefix=None
):
    permission_queryset = Permission.objects.filter(
        content_type__app_label=model._meta.app_label,
        codename__in=[codename for codename, dummy, dummy in permission_types]
    )

    if default_prefix is None:
        default_prefix = '%s_permissions' % model._meta.model_name

    class MultitenantCollectionMemberPermissionsForm(forms.Form):
        """
        For a given model with CollectionMember behaviour, defines the permissions that are assigned to an entity
        (i.e. group or user) for a specific collection
        """
        collection = forms.ModelChoiceField(queryset=Collection.objects.none())
        permissions = forms.ModelMultipleChoiceField(
            queryset=permission_queryset,
            required=False,
            widget=forms.CheckboxSelectMultiple
        )

        def __init__(self, *args, **kwargs):
            request = kwargs.pop('request')
            super(MultitenantCollectionMemberPermissionsForm, self).__init__(*args, **kwargs)

            # Limit the Collection list to the current Site's Collection, unless the current User is a superuser.
            queryset = Collection.objects.filter(name=request.site.hostname)
            if request.user.is_superuser:
                queryset = Collection.objects.all()
            self.fields['collection'].queryset = queryset

    GroupCollectionMemberPermissionFormSet = type(
        str('GroupCollectionMemberPermissionFormSet'),
        (MultitenantBaseGroupCollectionMemberPermissionFormSet, ),
        {
            'permission_types': permission_types,
            'permission_queryset': permission_queryset,
            'default_prefix': default_prefix,
            'template': template,
        }
    )

    return forms.formset_factory(
        MultitenantCollectionMemberPermissionsForm,
        formset=GroupCollectionMemberPermissionFormSet,
        extra=0,
        can_delete=True
    )

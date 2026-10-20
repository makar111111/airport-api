from django.contrib.auth.forms import (
    UserChangeForm as DjangoUserChangeForm,
    UserCreationForm as DjangoUserCreationForm,
)

from user.models import User


class NormalizedEmailMixin:
    def clean_email(self):
        return User.objects.normalize_email(self.cleaned_data["email"])


class UserCreationForm(NormalizedEmailMixin, DjangoUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)


class UserChangeForm(NormalizedEmailMixin, DjangoUserChangeForm):
    class Meta:
        model = User
        fields = "__all__"

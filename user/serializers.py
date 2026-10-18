from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class NormalizedEmailField(serializers.EmailField):
    def to_internal_value(self, data):
        email = super().to_internal_value(data)
        return get_user_model().objects.normalize_email(email)


class UserSerializer(serializers.ModelSerializer):
    email = NormalizedEmailField(validators=[
        UniqueValidator(queryset=get_user_model().objects.all())
    ])
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = get_user_model()
        fields = (
            "id", "email", "first_name", "last_name", "password", "is_staff"
        )
        read_only_fields = ("id", "is_staff")

    def validate(self, attrs):
        if "password" in attrs:
            candidate = get_user_model()(**{
                field: attrs.get(field, getattr(self.instance, field, ""))
                for field in ("email", "first_name", "last_name")
            })
            try:
                validate_password(attrs["password"], candidate)
            except DjangoValidationError as error:
                raise serializers.ValidationError(
                    {"password": error.messages}
                ) from error
        return attrs

    def create(self, validated_data):
        return get_user_model().objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password is not None:
            instance.set_password(password)
        instance.save()
        return instance


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        attrs[self.username_field] = get_user_model().objects.normalize_email(
            attrs[self.username_field]
        )
        return super().validate(attrs)


class TokenPairResponseSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)

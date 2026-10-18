from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from user.serializers import (
    EmailTokenObtainPairSerializer,
    TokenPairResponseSerializer,
    UserSerializer,
)


class CreateUserView(generics.CreateAPIView):
    serializer_class = UserSerializer
    permission_classes = (AllowAny,)


class ManageUserView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


@extend_schema(responses=TokenPairResponseSerializer)
class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer

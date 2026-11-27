from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_204_NO_CONTENT
from rest_framework.viewsets import GenericViewSet

from eduflow.api.v1.session.serializers import StaffLoginSerializer


@method_decorator([never_cache, csrf_protect], name="dispatch")
class SessionViewSet(GenericViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    serializer_class = StaffLoginSerializer

    def list(self, request: Request) -> Response:
        user = request.user
        return Response({
            "csrf_token": get_token(request),
            "permissions": {
                operation: user.is_staff and user.has_perm(f"applications.{operation}_application")
                for operation in ("add", "change", "delete")
            },
        })

    @action(detail=False, methods=["post"], url_path="login")
    def sign_in(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request=request, **serializer.validated_data)
        if user is None or not user.is_staff:
            raise AuthenticationFailed("운영자 계정 정보를 확인해 주세요.")
        login(request, user)
        return Response({"csrf_token": get_token(request)})

    @action(detail=False, methods=["post"], url_path="logout")
    def sign_out(self, request: Request) -> Response:
        logout(request)
        return Response(status=HTTP_204_NO_CONTENT)

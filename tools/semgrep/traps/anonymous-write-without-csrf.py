from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def enforce_csrf(request):
    SessionAuthentication().enforce_csrf(request)


class LoginView(APIView):
    permission_classes = [AllowAny]

    # ruleid: anonymous-write-without-csrf
    def post(self, request):
        return Response({"ok": True})

    # ok: anonymous-write-without-csrf
    def get(self, request):
        return Response({"csrf": "set"})


class SignupView(APIView):
    permission_classes = (AllowAny,)

    # ok: anonymous-write-without-csrf
    def post(self, request):
        enforce_csrf(request)
        return Response(status=201)


class WebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    # ok: anonymous-write-without-csrf
    def post(self, request):
        return Response(status=202)


class SessionLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication]

    # ruleid: anonymous-write-without-csrf
    def post(self, request):
        return Response({"ok": True})


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    # ok: anonymous-write-without-csrf
    def patch(self, request):
        return Response({"ok": True})

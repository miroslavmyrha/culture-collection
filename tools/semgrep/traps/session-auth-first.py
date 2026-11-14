from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

# ruleid: session-auth-first
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
}

# ok: session-auth-first
SCAFFOLD = {
    # The project's subclass answers anonymous requests with 401.
    "DEFAULT_AUTHENTICATION_CLASSES": ["proj.core.authentication.SessionAuthentication"],
}

# ok: session-auth-first
GOOD = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("proj.core.authentication.SessionWithHeader",),
}


class LegacyView(APIView):
    # ruleid: session-auth-first
    authentication_classes = [SessionAuthentication]

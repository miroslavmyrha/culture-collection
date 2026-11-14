from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class LoginView(APIView):
    # ruleid: scoped-throttle-without-scope
    throttle_classes = [ScopedRateThrottle]


class ExportView(APIView):
    # ok: scoped-throttle-without-scope
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "export"

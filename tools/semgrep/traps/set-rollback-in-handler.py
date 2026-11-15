from django.db import transaction
from rest_framework.views import exception_handler, set_rollback


def handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # ruleid: set-rollback-in-handler
        set_rollback()
    return response


def cancel_inside_atomic():
    with transaction.atomic():
        # ok: set-rollback-in-handler
        transaction.set_rollback(True)

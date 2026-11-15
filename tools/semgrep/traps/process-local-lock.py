import threading

from django.db import connection

# ruleid: process-local-lock
PLACEMENT_LOCK = threading.Lock()


def place(sample, position):
    with PLACEMENT_LOCK:
        position.sample = sample
        position.save()


def place_with_advisory_lock(sample, position):
    with connection.cursor() as cursor:
        # ok: process-local-lock
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [position.pk])

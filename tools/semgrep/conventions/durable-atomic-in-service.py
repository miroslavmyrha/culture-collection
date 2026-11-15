from django.db import transaction


def receive(sample):
    # ruleid: durable-atomic-in-service
    with transaction.atomic(durable=True):
        sample.save()


def store(sample):
    # ok: durable-atomic-in-service
    with transaction.atomic():
        sample.save()

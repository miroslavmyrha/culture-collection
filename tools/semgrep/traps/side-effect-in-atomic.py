from functools import partial

import requests
from django.core.mail import send_mail
from django.db import transaction

from .tasks import notify


def receive(sample, actor):
    with transaction.atomic():
        sample.save()
        # ruleid: side-effect-in-atomic
        notify.delay(sample.pk)
        # ruleid: side-effect-in-atomic
        send_mail("Received", "...", None, [actor.email])
        # ok: side-effect-in-atomic
        transaction.on_commit(lambda: notify.delay(sample.pk))


@transaction.atomic
def ship(samples):
    for sample in samples:
        sample.save()
        # ruleid: side-effect-in-atomic
        requests.post("https://courier.example/api", json={"id": sample.pk}, timeout=5)
        # ok: side-effect-in-atomic
        transaction.on_commit(partial(notify.delay, sample.pk))


def receive_with_callback(sample):
    with transaction.atomic():
        sample.save()

        def dispatch():
            # ok: side-effect-in-atomic
            notify.delay(sample.pk)

        transaction.on_commit(dispatch)


def after_commit(sample):
    # ok: side-effect-in-atomic
    notify.delay(sample.pk)

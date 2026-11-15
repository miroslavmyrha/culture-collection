from django.db import transaction
from django.db.models import F

from .models import Aliquot, Counter


def take(aliquot_id, volume):
    aliquot = Aliquot.objects.get(pk=aliquot_id)
    # ruleid: read-modify-write
    aliquot.volume_ul -= volume
    aliquot.save(update_fields=["volume_ul"])


def take_locked(aliquot_id, volume):
    with transaction.atomic():
        aliquot = Aliquot.objects.select_for_update().get(pk=aliquot_id)
        # ok: read-modify-write
        aliquot.volume_ul -= volume
        aliquot.save(update_fields=["volume_ul"])


def next_number(lab):
    with transaction.atomic():
        counter = Counter.objects.select_for_update().filter(lab=lab).first()
        # ok: read-modify-write
        counter.last_number += 1
        counter.save(update_fields=["last_number"])
        return counter.last_number


def take_with_f(aliquot_id, volume):
    # ok: read-modify-write
    Aliquot.objects.filter(pk=aliquot_id).update(volume_ul=F("volume_ul") - volume)

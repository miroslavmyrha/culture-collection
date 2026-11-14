from django.db import transaction

from .models import Sample


def move(sample_id, box):
    # ruleid: select-for-update-outside-atomic
    sample = Sample.objects.select_for_update().get(pk=sample_id)
    sample.box = box
    sample.save()


def move_safely(sample_id, box):
    with transaction.atomic():
        # ok: select-for-update-outside-atomic
        sample = Sample.objects.select_for_update().get(pk=sample_id)
        sample.box = box
        sample.save()


def store(sample_id, box):
    with audited_atomic():
        # ok: select-for-update-outside-atomic
        sample = Sample.objects.select_for_update().filter(pk=sample_id).first()
        sample.box = box
        sample.save()


def _locked(model, pk):
    # ok: select-for-update-outside-atomic
    return model._default_manager.select_for_update().filter(pk=pk).first()


def vials_leave_locked(strain):
    """The caller holds the transaction and the strain row."""
    # ok: select-for-update-outside-atomic
    return list(Sample.objects.select_for_update(of=("self",)).filter(strain=strain))


def audited_atomic(): ...


def locked_samples(box):
    # ok: select-for-update-outside-atomic
    return Sample.objects.select_for_update().filter(box=box)


def move_traced(sample_id, box):
    with traced_atomic_transaction():
        # ok: select-for-update-outside-atomic
        Sample.objects.select_for_update().get(pk=sample_id)


def traced_atomic_transaction(): ...


@transaction.atomic
def discard(sample_id):
    # ok: select-for-update-outside-atomic
    Sample.objects.select_for_update().filter(pk=sample_id).update(discarded=True)

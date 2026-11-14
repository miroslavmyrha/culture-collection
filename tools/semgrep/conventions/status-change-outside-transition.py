from django import forms
from django.db import transaction

from .models import AuditEvent, Sample

ALLOWED = {("received", "processing"), ("processing", "stored")}


def sample_transition(sample_id, to, actor, reason):
    with transaction.atomic():
        sample = Sample.objects.select_for_update().get(pk=sample_id)
        if (sample.status, to) not in ALLOWED:
            raise ValueError(f"{sample.status} -> {to} is not allowed")
        AuditEvent.objects.create(sample=sample, actor=actor, old=sample.status, new=to, reason=reason)
        # ok: status-change-outside-transition
        sample.status = to
        sample.save(update_fields=["status"])


def discard_all(box):
    # ruleid: status-change-outside-transition
    Sample.objects.filter(box=box).update(status="discarded")


class SampleSerializer:
    def update(self, instance, validated_data):
        # ruleid: status-change-outside-transition
        instance.status = validated_data["status"]
        instance.save()
        return instance


class TaxonForm(forms.ModelForm):
    def clean(self):
        data = super().clean() or {}
        # ok: status-change-outside-transition
        self.instance.status = "synonym" if data.get("accepted") else "accepted"
        return data

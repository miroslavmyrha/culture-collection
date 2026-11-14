from django.conf import settings
from django.db import models
from django.db.models import Q

from .base import PublicModel


class Report(models.Model):
    # ok: choices-without-check-constraint
    language = models.CharField(max_length=8, choices=settings.LANGUAGES)


class Sample(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received"
        STORED = "stored"

    # ruleid: choices-without-check-constraint
    status = models.CharField(max_length=12, choices=Status.choices)


class AuditEvent(models.Model):
    class Channel(models.TextChoices):
        WEB = "web"

    # ok: choices-without-check-constraint
    channel = models.CharField(max_length=20, choices=Channel.choices)

    class Meta:
        constraints = (
            models.CheckConstraint(condition=Q(channel__in=Channel.values), name="channel_valid"),
        )


class Package(models.Model):
    class Coolant(models.TextChoices):
        DRY_ICE = "dry_ice"

    # ok: choices-without-check-constraint
    coolant = models.CharField(max_length=20, choices=Coolant.choices, blank=True)

    class Meta(PublicModel.Meta):
        abstract = True


class Box(models.Model):
    class Kind(models.TextChoices):
        RACK = "rack"

    # ok: choices-without-check-constraint
    kind = models.CharField(max_length=8, choices=Kind.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=Kind.values), name="box_kind_valid"),
        ]

from django.contrib import admin
from django.db import models
from rest_framework import serializers


class Sample(models.Model):
    class Meta:
        # ruleid: ordering-without-pk
        ordering = ["-received_at"]


class Box(models.Model):
    class Meta:
        # ok: ordering-without-pk
        ordering = ["-received_at", "pk"]


class Rack(models.Model):
    class Meta:
        # ruleid: ordering-without-pk
        ordering = ("name",)


class SampleViewSet:
    # ok: ordering-without-pk
    ordering = ("name", "-id")


class SampleAdmin(admin.ModelAdmin):
    # ok: ordering-without-pk
    ordering = ("-received_at",)


SampleAdminBase = admin.ModelAdmin


@admin.register(Sample)
class TypedSampleAdmin(SampleAdminBase):
    # ok: ordering-without-pk
    ordering = ("name",)


class SampleQuery(serializers.Serializer):
    # ok: ordering-without-pk
    ordering = serializers.ChoiceField(choices=["name", "-name"])

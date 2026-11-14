from django import forms
from rest_framework import serializers

from .models import Sample


class SampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sample
        # ruleid: serializer-all-fields
        fields = "__all__"


class SampleAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sample
        # ruleid: serializer-all-fields
        exclude = ["donor"]


class SampleOutput(serializers.ModelSerializer):
    class Meta:
        model = Sample
        # ok: serializer-all-fields
        fields = ["public_id", "barcode", "status"]


class SampleForm(forms.ModelForm):
    class Meta:
        model = Sample
        # ok: serializer-all-fields
        fields = "__all__"

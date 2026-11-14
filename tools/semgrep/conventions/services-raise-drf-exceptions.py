# ruleid: services-raise-drf-exceptions
from rest_framework.exceptions import ValidationError

# ok: services-raise-drf-exceptions
from django.db import transaction


class PositionTaken(Exception):
    pass


def place(position, sample):
    with transaction.atomic():
        if position.sample_id:
            raise ValidationError("taken")
        position.sample = sample
        position.save()

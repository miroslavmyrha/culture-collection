from django.db import IntegrityError

from .models import Position


def place(box, row, col, sample):
    # ruleid: exists-then-create
    if not Position.objects.filter(box=box, row=row, col=col).exists():
        Position.objects.create(box=box, row=row, col=col, sample=sample)


def place_safely(box, row, col, sample):
    # ok: exists-then-create
    try:
        Position.objects.create(box=box, row=row, col=col, sample=sample)
    except IntegrityError:
        return None

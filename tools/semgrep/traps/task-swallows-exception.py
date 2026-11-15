import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task
def send_report(report_id):
    # ruleid: task-swallows-exception
    try:
        build(report_id)
    except Exception:
        log.exception("report %s failed", report_id)


@shared_task(bind=True)
def sync_courier(self, shipment_id):
    # ok: task-swallows-exception
    try:
        push(shipment_id)
    except Exception as exc:
        log.warning("courier down")
        raise self.retry(exc=exc) from exc


@shared_task
def sweep_expired():
    # ok: task-swallows-exception
    try:
        build(0)
    except Exception as exc:
        capture_exception(exc)


def capture_exception(exc): ...


def plain_helper(report_id):
    # ok: task-swallows-exception
    try:
        build(report_id)
    except Exception:
        log.exception("not a task")


def build(report_id): ...


def push(shipment_id): ...

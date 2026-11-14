import os
from pathlib import Path

from django.http import FileResponse

ROOT = Path("/srv/files")


def download(request):
    name = request.GET["name"]
    # ruleid: path-join-user-input
    return open(os.path.join(ROOT, name), "rb")


class ExportView:
    def get(self, request, *args, **kwargs):
        target = ROOT / self.kwargs["filename"]
        # ruleid: path-join-user-input
        return FileResponse(target.open("rb"))


def safe(request):
    name = os.path.basename(request.GET["name"])
    # ok: path-join-user-input
    return open(os.path.join(ROOT, name), "rb")


def upload(request):
    upload = request.FILES["file"]
    # ok: path-join-user-input
    return (ROOT / upload.name).write_bytes(upload.read())


def bucket(request, count):
    # ok: path-join-user-input
    return count / int(request.GET["per_page"])


def server_name():
    # ok: path-join-user-input
    return open(ROOT / "report.pdf", "rb")

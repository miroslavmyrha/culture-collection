import os
from pathlib import Path

import environ

# ruleid: environ-file-aware-env
env = environ.FileAwareEnv()


def secret(name):
    path = os.environ.get(f"{name}_FILE")
    if path:
        # ok: environ-file-aware-env
        return Path(path).read_text().strip()
    return os.environ[name]

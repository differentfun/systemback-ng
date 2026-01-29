import fcntl
from pathlib import Path


class Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = self.path.open("w")
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.fd.write("locked\n")
        self.fd.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                self.fd.close()

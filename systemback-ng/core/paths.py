import os
from pathlib import Path
from .config import Config


def ensure_runtime_dirs(cfg: Config) -> None:
    for path in (cfg.state_dir, cfg.snapshots_dir):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except PermissionError:
            if os.geteuid() == 0:
                raise

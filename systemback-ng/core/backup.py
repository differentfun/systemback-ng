import logging
import shutil
import time
import subprocess
from pathlib import Path

from .config import Config
from .lock import Lock
from .snapshots import latest_snapshot
from .utils import read_list_file, run, require_root, has_mountpoint


def backup(cfg: Config, label: str, progress: bool = False) -> None:
    require_root()

    with Lock(cfg.state_dir / "lock"):
        # Guard against writing to non-mounted external paths
        for p in (cfg.snapshots_dir,):
            if str(p).startswith("/media/") or str(p).startswith("/mnt/"):
                if not has_mountpoint(p):
                    raise SystemExit(f"Target path is not on a mounted filesystem: {p}")
        base = latest_snapshot(cfg)
        ts = time.strftime("%Y%m%d-%H%M%S")
        safe_label = label.strip().lower().replace(" ", "_") if label and label != "auto" else ""
        name = f"{ts}_{safe_label}.tar.zst" if safe_label else f"{ts}.tar.zst"
        snap_path = cfg.snapshots_dir / name
        logging.info("Backup start: %s (base=%s) -> %s", name, base.id if base else "-", snap_path)

        cmd = [
            "tar",
            "--xattrs",
            "--acls",
            "--numeric-owner",
            "--one-file-system",
            "-I",
            "zstd",
            "-cpf",
            str(snap_path),
        ]

        if cfg.excludes_path.exists():
            cmd += ["--exclude-from", str(cfg.excludes_path)]

        # Always avoid snapshot/state dirs to prevent recursion
        cmd += ["--exclude", str(cfg.state_dir)]
        cmd += ["--exclude", str(cfg.snapshots_dir)]
        cmd += ["/"]

        try:
            proc = subprocess.run(cmd)
            if proc.returncode not in (0, 1):
                raise subprocess.CalledProcessError(proc.returncode, cmd)
            if proc.returncode == 1:
                logging.warning("Backup completed with warnings (tar exit code 1).")
            run(["sh", "-c", f"sha256sum {snap_path} > {snap_path}.sha256"])
            logging.info("Backup complete: %s", snap_path)
        except Exception:
            logging.error("Backup failed, cleaning snapshot file: %s", snap_path)
            try:
                if snap_path.exists():
                    snap_path.unlink()
            except Exception:
                pass
            raise

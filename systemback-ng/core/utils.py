import logging
import os
import re
import shutil
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("This command must be run as root.")


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd: list[str]) -> None:
    logging.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_env(cmd: list[str], env: dict[str, str]) -> None:
    logging.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def read_list_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def pkg_installed(pkg: str) -> bool:
    res = subprocess.run(["dpkg-query", "-W", "-f=${Status}", pkg], capture_output=True, text=True)
    return res.returncode == 0 and "install ok installed" in res.stdout


def apt_install(pkgs: list[str]) -> int:
    cmd = ["pkexec", "apt", "install", "-y"] + pkgs
    logging.info("Installing packages: %s", " ".join(pkgs))
    return subprocess.call(cmd)


def run_rsync_with_progress(cmd: list[str]) -> None:
    logging.info("Running (progress): %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if not proc.stdout:
        raise SystemExit("Failed to capture rsync output for progress.")
    for line in proc.stdout:
        line = line.rstrip()
        logging.info("rsync: %s", line)
        pct = None
        m = re.search(r"(\\d{1,3})%\\s", line)
        if m:
            try:
                pct = max(0, min(100, int(m.group(1))))
            except Exception:
                pct = None
        if pct is None and "to-chk=" in line:
            try:
                part = line.split("to-chk=")[-1]
                remain_str, total_str = part.split("/")[:2]
                remain = int(remain_str)
                total = int(total_str)
                if total > 0:
                    pct = int((total - remain) * 100 / total)
            except Exception:
                pct = None
        if pct is not None:
            sys.stdout.write(f"SBPROGRESS {pct} {line}\n")
            sys.stdout.flush()
    rc = proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def sanitize_label(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"[^a-z0-9._-]+", "_", label)
    return label[:40] if label else "auto"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def has_mountpoint(path: Path) -> bool:
    cur = path.resolve()
    while cur != cur.parent:
        if cur.is_mount():
            return True
        cur = cur.parent
    return cur.is_mount()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def temp_filter_file(rules: Iterable[str], path: Path) -> Path:
    write_text(path, "\n".join(rules) + "\n")
    return path

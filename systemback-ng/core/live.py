import logging
import os
import shutil
import time
from pathlib import Path

from .config import Config
from .snapshots import latest_snapshot, list_snapshots
from .utils import ensure_dir, require_root, run, read_list_file, write_text, which, pkg_installed, has_mountpoint


def _find_snapshot(cfg: Config, snap_id: str | None):
    if snap_id:
        for s in list_snapshots(cfg):
            if s.id == snap_id:
                return s
        raise SystemExit(f"Snapshot not found: {snap_id}")
    snap = latest_snapshot(cfg)
    if not snap:
        raise SystemExit("No snapshots available.")
    return snap


def _kernel_paths() -> tuple[Path, Path]:
    kver = os.uname().release
    vmlinuz = Path(f"/boot/vmlinuz-{kver}")
    initrd = Path(f"/boot/initrd.img-{kver}")
    if not vmlinuz.exists() or not initrd.exists():
        raise SystemExit("Kernel or initrd not found in /boot. Ensure the system kernel is installed.")
    return vmlinuz, initrd


def _ensure_live_boot() -> None:
    if Path("/usr/share/initramfs-tools/scripts/init-bottom/live").exists() or Path("/usr/share/initramfs-tools/scripts/live").exists():
        return
    if pkg_installed("live-boot"):
        logging.info("live-boot installed but initramfs not updated. Running update-initramfs -u.")
        if Path("/usr/sbin/update-initramfs").exists():
            run(["/usr/sbin/update-initramfs", "-u"])
        else:
            run(["sh", "-c", "PATH=/usr/sbin:/usr/bin:/sbin:/bin update-initramfs -u"])
        if Path("/usr/share/initramfs-tools/scripts/init-bottom/live").exists() or Path("/usr/share/initramfs-tools/scripts/live").exists():
            return
        raise SystemExit("live-boot installed but initramfs still missing live hook after update.")
    raise SystemExit("live-boot not found. Install live-boot and run update-initramfs -u.")


def _build_squashfs(snapshot_path: Path, target: Path, excludes: list[str], compression: str) -> None:
    logging.info("Building squashfs: %s -> %s (comp=%s)", snapshot_path, target, compression)
    cmd = ["mksquashfs", str(snapshot_path), str(target), "-noappend", "-b", "1M"]
    if compression != "none":
        cmd += ["-comp", compression]
    for exc in excludes:
        cmd += ["-e", exc]
    run(cmd)


def _build_grub_cfg(path: Path, title: str) -> None:
    text = f"""set default=0
set timeout=5

menuentry \"{title}\" {{
    linux /live/vmlinuz boot=live components quiet splash
    initrd /live/initrd.img
}}
"""
    write_text(path, text)


def create_live_iso(cfg: Config, snapshot_id: str | None, name: str, compression: str = "zstd") -> Path:
    require_root()

    if not which("mksquashfs") or not which("grub-mkrescue"):
        raise SystemExit("Missing required tools: mksquashfs and grub-mkrescue")

    _ensure_live_boot()
    if str(cfg.iso_dir).startswith("/media/") or str(cfg.iso_dir).startswith("/mnt/"):
        if not has_mountpoint(cfg.iso_dir):
            raise SystemExit(f"ISO directory is not on a mounted filesystem: {cfg.iso_dir}")
    snap = _find_snapshot(cfg, snapshot_id)
    vmlinuz, initrd = _kernel_paths()
    logging.info("Live ISO paths: snapshots_dir=%s iso_dir=%s work_dir=%s", cfg.snapshots_dir, cfg.iso_dir, cfg.live_work_dir)
    logging.info("Live ISO snapshot: %s at %s", snap.id, snap.path)
    logging.info("Creating live ISO from snapshot: %s", snap.id)

    ts = time.strftime("%Y%m%d-%H%M%S")
    if name == "auto":
        name = f"systemback-ng_{ts}"

    work = cfg.live_work_dir / f"build_{ts}"
    iso_root = work / "iso_root"
    live_dir = iso_root / "live"
    grub_dir = iso_root / "boot" / "grub"

    ensure_dir(live_dir)
    ensure_dir(grub_dir)

    (live_dir / "vmlinuz").write_bytes(vmlinuz.read_bytes())
    (live_dir / "initrd.img").write_bytes(initrd.read_bytes())

    excludes = read_list_file(cfg.excludes_path)
    # avoid snapshot recursion and runtime dirs
    excludes += [str(cfg.state_dir), "/proc", "/sys", "/dev", "/run", "/tmp"]

    ensure_dir(cfg.iso_dir)
    iso_path = cfg.iso_dir / f"{name}.iso"
    try:
        _build_squashfs(snap.path, live_dir / "filesystem.squashfs", excludes, compression)
        _build_grub_cfg(grub_dir / "grub.cfg", "Systemback-ng Live")

        logging.info("Live ISO output: %s", iso_path)
        squashfs_path = live_dir / "filesystem.squashfs"
        extra_opts: list[str] = []
        if squashfs_path.exists() and squashfs_path.stat().st_size > 4 * 1024 * 1024 * 1024:
            logging.info("filesystem.squashfs > 4GiB, using ISO level 3 + UDF")
            extra_opts = ["-iso-level", "3", "-udf"]
        cmd = ["grub-mkrescue", "-o", str(iso_path)] + extra_opts + [str(iso_root)]
        run(cmd)
        logging.info("ISO created at: %s", iso_path)
        return iso_path
    except Exception:
        logging.error("Live ISO build failed, cleaning workdir and partial ISO")
        shutil.rmtree(work, ignore_errors=True)
        try:
            if iso_path.exists():
                iso_path.unlink()
        except Exception:
            pass
        raise


def _check_block_device(dev: Path) -> None:
    if not dev.exists():
        raise SystemExit(f"Device not found: {dev}")
    if not dev.is_block_device():
        raise SystemExit(f"Not a block device: {dev}")


def write_live_usb(cfg: Config, snapshot_id: str | None, device: str, force: bool, compression: str = "zstd") -> Path:
    require_root()

    if not force:
        raise SystemExit("Refusing to write to device without --force.")

    dev = Path(device)
    _check_block_device(dev)

    iso_path = create_live_iso(cfg, snapshot_id, "auto", compression=compression)

    # Use dd for raw write
    logging.info("Live USB target device: %s", dev)
    run(["dd", f"if={iso_path}", f"of={dev}", "bs=4M", "status=progress", "oflag=sync"])
    run(["sync"])
    logging.info("USB written to: %s", dev)
    return iso_path

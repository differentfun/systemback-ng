import json
import logging
import os
import time
import subprocess
from pathlib import Path

from .config import Config
from .lock import Lock
from .snapshots import list_snapshots
from .utils import read_list_file, run, require_root, is_subpath


def find_snapshot(cfg: Config, snap_id: str):
    for snap in list_snapshots(cfg):
        if snap.id == snap_id:
            return snap
    return None


def _lsblk_json() -> dict:
    out = os.popen("lsblk -J -o NAME,PATH,SIZE,TYPE,MOUNTPOINT,PKNAME").read()
    return json.loads(out) if out else {"blockdevices": []}


def _parent_disk(part: Path) -> Path:
    out = os.popen(f"lsblk -no PKNAME {part}").read().strip()
    if not out:
        raise SystemExit(f"Cannot determine parent disk for {part}")
    return Path(f"/dev/{out}")


def _device_size_mib(dev: Path) -> int:
    out = os.popen(f"blockdev --getsize64 {dev}").read().strip()
    size_bytes = int(out)
    return size_bytes // (1024 * 1024)


def _wait_block_devices(dev: Path) -> None:
    run(["partprobe", str(dev)])
    run(["udevadm", "settle"])


def _list_partitions(dev: Path) -> list[Path]:
    res = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,PATH,TYPE,PKNAME", str(dev)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if res.returncode != 0:
        return []
    try:
        data = json.loads(res.stdout)
    except Exception:
        return []
    parts: list[Path] = []
    dev_name = dev.name
    for blk in data.get("blockdevices", []):
        children = blk.get("children") or []
        for ch in children:
            if ch.get("type") == "part" and ch.get("pkname") == dev_name:
                path = ch.get("path")
                if path:
                    parts.append(Path(path))
    return sorted(parts, key=lambda p: p.name)


def _mkfs(fs: str, device: Path) -> None:
    if fs == "ext4":
        run(["mkfs.ext4", "-F", str(device)])
    elif fs == "xfs":
        run(["mkfs.xfs", "-f", str(device)])
    elif fs == "btrfs":
        run(["mkfs.btrfs", "-f", str(device)])
    else:
        raise SystemExit(f"Unsupported filesystem: {fs}")


def _detect_fs(dev: Path) -> str | None:
    out = os.popen(f"blkid -s TYPE -o value {dev}").read().strip()
    return out or None


def _format_esp(dev: Path) -> None:
    run(["mkfs.vfat", "-F", "32", str(dev)])


def _format_swap(dev: Path) -> None:
    run(["mkswap", str(dev)])


def _mount(dev: Path, mountpoint: Path) -> None:
    mountpoint.mkdir(parents=True, exist_ok=True)
    run(["mount", str(dev), str(mountpoint)])


def _bind_mount(src: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    run(["mount", "--bind", src, str(target)])


def _umount(path: Path) -> None:
    run(["umount", "-lf", str(path)])


def _write_fstab(root: Path, root_dev: Path, fs: str, esp_dev: Path | None, swap_dev: Path | None) -> None:
    def _uuid(dev: Path) -> str:
        return os.popen(f"blkid -s UUID -o value {dev}").read().strip()

    lines = []
    root_uuid = _uuid(root_dev)
    lines.append(f"UUID={root_uuid} / {fs} defaults 0 1")
    if esp_dev:
        esp_uuid = _uuid(esp_dev)
        lines.append(f"UUID={esp_uuid} /boot/efi vfat umask=0077 0 1")
    if swap_dev:
        swap_uuid = _uuid(swap_dev)
        lines.append(f"UUID={swap_uuid} none swap sw 0 0")
    fstab = root / "etc" / "fstab"
    fstab.parent.mkdir(parents=True, exist_ok=True)
    fstab.write_text("\n".join(lines) + "\n")


def _install_grub(root: Path, boot: str, target_disk: Path, esp_mount: Path | None) -> None:
    _bind_mount("/dev", root / "dev")
    _bind_mount("/proc", root / "proc")
    _bind_mount("/sys", root / "sys")
    _bind_mount("/run", root / "run")
    try:
        if boot == "uefi":
            if not esp_mount:
                raise SystemExit("EFI mount missing for UEFI install")
            run([
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory",
                str(esp_mount),
                "--boot-directory",
                str(root / "boot"),
                "--bootloader-id",
                "systemback-ng",
            ])
            # Also install fallback bootloader for UEFI environments that ignore NVRAM entries (e.g. some VMs).
            run([
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory",
                str(esp_mount),
                "--boot-directory",
                str(root / "boot"),
                "--bootloader-id",
                "systemback-ng",
                "--removable",
                "--no-nvram",
            ])
        else:
            run(["grub-install", "--target=i386-pc", str(target_disk), "--boot-directory", str(root / "boot")])
        run(["chroot", str(root), "update-grub"])
    finally:
        for p in ("dev", "proc", "sys", "run"):
            try:
                _umount(root / p)
            except Exception:
                pass


def _partition_disk(dev: Path, boot: str, fs: str, swap_mib: int, esp_mib: int) -> tuple[Path, Path | None, Path | None]:
    run(["wipefs", "-a", str(dev)])
    if boot == "uefi":
        run(["parted", "-s", str(dev), "mklabel", "gpt"])
        start_esp = 1
        end_esp = start_esp + esp_mib
        size_mib = _device_size_mib(dev)
        end_root = size_mib - swap_mib - 1 if swap_mib > 0 else size_mib - 1
        run(["parted", "-s", str(dev), "mkpart", "ESP", "fat32", f"{start_esp}MiB", f"{end_esp}MiB"])
        run(["parted", "-s", str(dev), "set", "1", "esp", "on"])
        run(["parted", "-s", str(dev), "mkpart", "root", f"{end_esp}MiB", f"{end_root}MiB"])
        if swap_mib > 0:
            run(["parted", "-s", str(dev), "mkpart", "swap", "linux-swap", f"{end_root}MiB", "100%"])
    else:
        run(["parted", "-s", str(dev), "mklabel", "msdos"])
        size_mib = _device_size_mib(dev)
        end_root = size_mib - swap_mib - 1 if swap_mib > 0 else size_mib - 1
        run(["parted", "-s", str(dev), "mkpart", "primary", f"1MiB", f"{end_root}MiB"])
        if swap_mib > 0:
            run(["parted", "-s", str(dev), "mkpart", "primary", "linux-swap", f"{end_root}MiB", "100%"])
            run(["parted", "-s", str(dev), "set", "2", "swap", "on"])
    _wait_block_devices(dev)
    parts: list[Path] = []
    for _ in range(10):
        parts = _list_partitions(dev)
        if parts:
            break
        time.sleep(0.5)
        _wait_block_devices(dev)
    if not parts:
        raise SystemExit(f"Failed to detect partitions for {dev} after partitioning.")
    if boot == "uefi":
        esp = parts[0]
        root = parts[1]
        swap = parts[2] if swap_mib > 0 and len(parts) > 2 else None
        _format_esp(esp)
    else:
        root = parts[0]
        swap = parts[1] if swap_mib > 0 and len(parts) > 1 else None
        esp = None
    _mkfs(fs, root)
    if swap:
        _format_swap(swap)
    return root, esp, swap


def _extract_snapshot(snapshot: Path, target_root: Path) -> None:
    run(["tar", "--xattrs", "--acls", "--numeric-owner", "-I", "zstd", "-xpf", str(snapshot), "-C", str(target_root)])


def _verify_snapshot(snapshot: Path) -> None:
    checksum = Path(str(snapshot) + ".sha256")
    if not checksum.exists():
        logging.warning("No checksum file found for snapshot: %s", checksum)
        return
    run(["sh", "-c", f"cd {snapshot.parent} && sha256sum -c {checksum.name}"])


def restore(
    cfg: Config,
    snap_id: str,
    mode: str,
    target: Path,
    boot: str,
    fs: str,
    swap_mib: int,
    esp_mib: int,
    efi_part: Path | None,
    swap_part: Path | None,
    progress: bool = False,
) -> None:
    require_root()

    snap = find_snapshot(cfg, snap_id)
    if not snap:
        raise SystemExit(f"Snapshot not found: {snap_id}")

    with Lock(cfg.state_dir / "lock"):
        logging.info("Restore start: snapshot=%s source=%s mode=%s target=%s boot=%s fs=%s", snap.id, snap.path, mode, target, boot, fs)
        root_mount = Path("/mnt/systemback-ng-root")
        root_mount.mkdir(parents=True, exist_ok=True)

        _verify_snapshot(snap.path)

        if mode == "disk":
            root_part, esp_part, swap_part = _partition_disk(target, boot, fs, swap_mib, esp_mib)
        else:
            root_part = target
            esp_part = efi_part if boot == "uefi" else None
            swap_part = swap_part

        if mode != "disk":
            _mkfs(fs, root_part)
        _mount(root_part, root_mount)
        esp_mount = None
        if boot == "uefi":
            if not esp_part:
                raise SystemExit("EFI partition is required for UEFI restore")
            esp_mount = root_mount / "boot" / "efi"
            _format_esp(esp_part) if mode == "disk" else None
            _mount(esp_part, esp_mount)
        if swap_part:
            _format_swap(swap_part)

        try:
            _extract_snapshot(snap.path, root_mount)
            _write_fstab(root_mount, root_part, fs, esp_part if boot == "uefi" else None, swap_part)
            _install_grub(root_mount, boot, _parent_disk(root_part), esp_mount)
        finally:
            try:
                if esp_mount:
                    _umount(esp_mount)
            except Exception:
                pass
            try:
                _umount(root_mount)
            except Exception:
                pass
        logging.info("Restore complete: %s", snap.id)

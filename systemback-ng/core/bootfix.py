import json
import logging
import subprocess
from pathlib import Path

from .config import Config
from .utils import require_root, run


def _lsblk(dev: Path) -> dict:
    res = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,PATH,TYPE,FSTYPE,PARTTYPE,PKNAME", str(dev)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if res.returncode != 0 or not res.stdout.strip():
        raise SystemExit(f"lsblk failed for {dev}: {res.stderr.strip()}")
    try:
        return json.loads(res.stdout)
    except Exception:
        raise SystemExit("Failed to parse lsblk output.")


def _detect_partitions(dev: Path) -> tuple[Path | None, Path | None]:
    data = _lsblk(dev)
    esp: Path | None = None
    root: Path | None = None
    for blk in data.get("blockdevices", []):
        for ch in blk.get("children") or []:
            if ch.get("type") != "part" or ch.get("pkname") != dev.name:
                continue
            path = Path(ch.get("path", ""))
            fstype = (ch.get("fstype") or "").lower()
            parttype = (ch.get("parttype") or "").lower()
            if parttype == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" or fstype in ("vfat", "fat32"):
                if esp is None:
                    esp = path
                else:
                    raise SystemExit("Multiple EFI System Partitions detected. Use --esp-part.")
            if fstype in ("ext4", "xfs", "btrfs"):
                if root is None:
                    root = path
                else:
                    raise SystemExit("Multiple Linux root partitions detected. Use --root-part.")
    return esp, root


def boot_fix(
    cfg: Config,
    disk: Path,
    boot: str,
    root_part: Path | None = None,
    esp_part: Path | None = None,
) -> None:
    require_root()
    if not disk.exists():
        raise SystemExit(f"Disk not found: {disk}")
    if not disk.is_block_device():
        raise SystemExit(f"Not a block device: {disk}")

    if root_part is None or (boot == "uefi" and esp_part is None):
        auto_esp, auto_root = _detect_partitions(disk)
        if root_part is None:
            root_part = auto_root
        if boot == "uefi" and esp_part is None:
            esp_part = auto_esp

    if root_part is None:
        raise SystemExit("Root partition not detected. Use --root-part.")
    if boot == "uefi" and esp_part is None:
        raise SystemExit("EFI System Partition not detected. Use --esp-part.")

    root_mount = Path("/mnt/systemback-ng-root")
    esp_mount = root_mount / "boot" / "efi"
    root_mount.mkdir(parents=True, exist_ok=True)

    logging.info("Boot fix: disk=%s boot=%s root=%s esp=%s", disk, boot, root_part, esp_part)

    run(["mount", str(root_part), str(root_mount)])
    try:
        if boot == "uefi":
            esp_mount.mkdir(parents=True, exist_ok=True)
            run(["mount", str(esp_part), str(esp_mount)])

        for p in ("/dev", "/proc", "/sys", "/run"):
            run(["mount", "--bind", p, str(root_mount / p.lstrip("/"))])

        if boot == "uefi":
            run([
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory",
                str(esp_mount),
                "--boot-directory",
                str(root_mount / "boot"),
                "--bootloader-id",
                "systemback-ng",
            ])
            run([
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory",
                str(esp_mount),
                "--boot-directory",
                str(root_mount / "boot"),
                "--bootloader-id",
                "systemback-ng",
                "--removable",
                "--no-nvram",
            ])
        else:
            run(["grub-install", "--target=i386-pc", str(disk), "--boot-directory", str(root_mount / "boot")])

        run(["chroot", str(root_mount), "update-grub"])
        logging.info("Boot fix complete.")
    finally:
        for p in ("dev", "proc", "sys", "run"):
            try:
                run(["umount", "-lf", str(root_mount / p)])
            except Exception:
                pass
        if boot == "uefi":
            try:
                run(["umount", "-lf", str(esp_mount)])
            except Exception:
                pass
        try:
            run(["umount", "-lf", str(root_mount)])
        except Exception:
            pass

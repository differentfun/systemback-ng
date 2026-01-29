import argparse
import logging
import sys

from pathlib import Path

from .backup import backup
from .bootfix import boot_fix
from .config import load_config
from .doctor import doctor
from .logging import setup_logging
from .paths import ensure_runtime_dirs
from .restore import restore
from .snapshots import list_snapshots


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="systemback-ng")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List snapshots")

    b = sub.add_parser("backup", help="Create a new snapshot")
    b.add_argument("--label", default="auto", help="Snapshot label")
    b.add_argument("--progress", action="store_true", help="Emit progress markers to stdout")
    b.add_argument("--snapshots-dir", help="Override snapshots directory")

    r = sub.add_parser("restore", help="Restore a snapshot")
    r.add_argument("--snapshot", required=True, help="Snapshot ID (file name)")
    r.add_argument("--mode", choices=["disk", "partition"], required=True, help="Restore target type")
    r.add_argument("--target", required=True, help="Target disk or partition, e.g. /dev/sdX or /dev/sdX1")
    r.add_argument("--boot", choices=["mbr", "uefi"], required=True, help="Boot mode")
    r.add_argument("--filesystem", choices=["ext4", "xfs", "btrfs"], default="ext4", help="Root filesystem type")
    r.add_argument("--swap-mib", type=int, default=0, help="Swap size in MiB (0 to disable)")
    r.add_argument("--esp-mib", type=int, default=512, help="ESP size in MiB (UEFI only)")
    r.add_argument("--efi-part", help="Existing EFI System Partition (UEFI + partition mode)")
    r.add_argument("--swap-part", help="Existing swap partition (partition mode)")
    r.add_argument("--progress", action="store_true", help="Emit progress markers to stdout")

    sub.add_parser("doctor", help="Check system dependencies and configuration")

    bf = sub.add_parser("boot-fix", help="Reinstall bootloader on a target disk")
    bf.add_argument("--disk", required=True, help="Target disk, e.g. /dev/sdX")
    bf.add_argument("--boot", choices=["mbr", "uefi"], required=True, help="Boot mode")
    bf.add_argument("--root-part", help="Root partition (optional, auto-detect if possible)")
    bf.add_argument("--esp-part", help="EFI System Partition (UEFI only, optional if auto-detect)")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    cfg = load_config()
    setup_logging(cfg)
    ensure_runtime_dirs(cfg)
    if getattr(args, "snapshots_dir", None):
        cfg.snapshots_dir = Path(args.snapshots_dir)

    logging.info("CLI command: %s", args.cmd)
    logging.info("Paths: snapshots=%s state=%s", cfg.snapshots_dir, cfg.state_dir)

    if args.cmd == "list":
        for s in list_snapshots(cfg):
            print(f"{s.id}\t{s.label}\t{int(s.created)}")
        return 0

    if args.cmd == "backup":
        ensure_runtime_dirs(cfg)
        backup(cfg, args.label, progress=args.progress)
        return 0

    if args.cmd == "restore":
        restore(
            cfg,
            args.snapshot,
            args.mode,
            Path(args.target),
            args.boot,
            args.filesystem,
            args.swap_mib,
            args.esp_mib,
            Path(args.efi_part) if args.efi_part else None,
            Path(args.swap_part) if args.swap_part else None,
            progress=args.progress,
        )
        return 0

    if args.cmd == "doctor":
        return doctor(cfg)

    if args.cmd == "boot-fix":
        boot_fix(
            cfg,
            Path(args.disk),
            args.boot,
            Path(args.root_part) if args.root_part else None,
            Path(args.esp_part) if args.esp_part else None,
        )
        return 0

    print(f"Not implemented yet: {args.cmd}")
    return 0

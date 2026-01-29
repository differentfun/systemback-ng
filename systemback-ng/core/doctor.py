from .config import Config
from .utils import which

REQUIRED_BACKUP = [
    "tar",
    "zstd",
    "sha256sum",
]

REQUIRED_RESTORE = [
    "tar",
    "zstd",
    "sha256sum",
    "lsblk",
    "blockdev",
    "parted",
    "wipefs",
    "partprobe",
    "udevadm",
    "mkfs.ext4",
    "mkfs.vfat",
    "mkswap",
    "grub-install",
    "update-grub",
    "blkid",
]

OPTIONAL = [
    "mkfs.xfs",
    "mkfs.btrfs",
]


def _check_group(title: str, cmds: list[str]) -> list[str]:
    missing = [cmd for cmd in cmds if not which(cmd)]
    if missing:
        print(f"Missing {title} commands:")
        for cmd in missing:
            print(f"- {cmd}")
    return missing


def doctor(cfg: Config) -> int:
    missing_any = False

    if _check_group("backup", REQUIRED_BACKUP):
        missing_any = True

    if _check_group("restore", REQUIRED_RESTORE):
        missing_any = True

    optional_missing = [cmd for cmd in OPTIONAL if not which(cmd)]
    if optional_missing:
        print("Optional commands missing:")
        for cmd in optional_missing:
            print(f"- {cmd}")

    if missing_any:
        return 1

    print("All required commands found.")
    return 0

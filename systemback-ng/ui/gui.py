import json
import logging
import os
import subprocess
from pathlib import Path

from core.config import load_config
from core.snapshots import list_snapshots
from core.logging import setup_logging

BIN = str(Path(__file__).resolve().parents[1] / "bin" / "systemback-ng")


def _zenity(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["zenity"] + args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _error(msg: str) -> None:
    logging.error(msg)
    _zenity(["--error", "--text", msg])


def _info(msg: str) -> None:
    logging.info(msg)
    _zenity(["--info", "--text", msg])


def _select_snapshot(cfg) -> str | None:
    snaps = _list_snapshots_root()
    if not snaps:
        _error("No snapshots available.")
        return None
    rows = []
    for s in snaps:
        rows += [s["id"], s["label"] or "-", str(int(s["created"]))]
    res = _zenity([
        "--list",
        "--title", "Select snapshot",
        "--text", "Select a snapshot to restore:",
        "--column", "ID",
        "--column", "Label",
        "--column", "Created",
    ] + rows)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _list_snapshots_root() -> list[dict]:
    cmd = [
        "stdbuf",
        "-oL",
        "-eL",
        BIN,
        "list",
    ]
    res = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        logging.error("Snapshot list failed: rc=%s stdout=%s stderr=%s", res.returncode, res.stdout, res.stderr)
        return []
    snaps = []
    for line in res.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 3:
            snaps.append({"id": parts[0], "label": parts[1], "created": parts[2]})
    return snaps


def _root_device() -> str | None:
    res = subprocess.run(
        ["findmnt", "-no", "SOURCE", "/"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if res.returncode != 0:
        logging.error("findmnt failed: rc=%s stdout=%s stderr=%s", res.returncode, res.stdout, res.stderr)
        return None
    src = res.stdout.strip()
    if not src:
        return None
    if src.startswith("/dev/") and src[5:].startswith("mapper/"):
        # Map device-mapper root to parent disk.
        res = subprocess.run(
            ["lsblk", "-no", "PKNAME", src],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if res.returncode == 0:
            pk = res.stdout.strip()
            return f"/dev/{pk}" if pk else src
    if src.startswith("/dev/") and src[5:].startswith("dm-"):
        res = subprocess.run(
            ["lsblk", "-no", "PKNAME", src],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if res.returncode == 0:
            pk = res.stdout.strip()
            return f"/dev/{pk}" if pk else src
    if src.startswith("/dev/"):
        res = subprocess.run(
            ["lsblk", "-no", "PKNAME", src],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if res.returncode == 0:
            pk = res.stdout.strip()
            return f"/dev/{pk}" if pk else src
    return src


def _list_disks() -> list[dict]:
    res = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,MOUNTPOINT"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if res.returncode != 0:
        logging.error("Disk list failed: rc=%s stdout=%s stderr=%s", res.returncode, res.stdout, res.stderr)
        return []
    try:
        data = json.loads(res.stdout)
    except Exception:
        logging.error("Failed to parse lsblk JSON output.")
        return []
    disks = []
    sys_disk = _root_device()
    for dev in data.get("blockdevices", []):
        if dev.get("type") == "disk":
            path = dev.get("path", "")
            if sys_disk and path == sys_disk:
                continue
            disks.append(
                {
                    "name": dev.get("name", ""),
                    "path": path,
                    "size": dev.get("size", ""),
                    "model": (dev.get("model") or "").strip(),
                    "tran": dev.get("tran") or "",
                    "rm": "yes" if str(dev.get("rm", "")).strip() in ("1", "True", "true", "yes") else "no",
                }
            )
    return disks


def _select_disk() -> str | None:
    disks = _list_disks()
    if not disks:
        _error("No disks detected. Please enter the device path manually (e.g. /dev/sdX).")
        return None
    rows = []
    for d in disks:
        rows += [d["name"], d["path"], d["size"], d["model"] or "-", d["tran"] or "-", d["rm"]]
    res = _zenity([
        "--list",
        "--title", "Select target disk",
        "--text", "Select the target disk:",
        "--width", "500",
        "--print-column", "2",
        "--column", "Disk",
        "--column", "Device",
        "--column", "Size",
        "--column", "Model",
        "--column", "Tran",
        "--column", "Removable",
        "--height", "400",
    ] + rows)
    if res.returncode != 0:
        return None
    selected = res.stdout.strip()
    return selected or None


def _edit_file_with_root(path: str, title: str) -> None:
    if not os.environ.get("DISPLAY"):
        _error("No DISPLAY found. Please run the GUI inside a graphical session.")
        return
    xauth = os.environ.get("XAUTHORITY", str(Path.home() / ".Xauthority"))
    editor = (
        "sh -c 'if command -v gedit >/dev/null 2>&1; then exec gedit {p} 2>/dev/null; "
        "elif command -v xed >/dev/null 2>&1; then exec xed {p} 2>/dev/null; "
        "elif command -v mousepad >/dev/null 2>&1; then exec mousepad {p} 2>/dev/null; "
        "elif command -v nano >/dev/null 2>&1; then exec xterm -e nano {p}; "
        "else exec xterm -e sh -c \"vi {p}\"; fi'"
    ).format(p=path)
    subprocess.call(
        [
            "env",
            f"DISPLAY={os.environ.get('DISPLAY')}",
            f"XAUTHORITY={xauth}",
            "sh",
            "-c",
            editor,
        ]
    )


def _write_config_paths(snapshots_dir: str) -> None:
    cfg_text = (
        "[paths]\n"
        "state_dir = /var/lib/systemback-ng\n"
        f"snapshots_dir = {snapshots_dir}\n"
        "log_file = /var/log/systemback-ng.log\n"
        "includes = /etc/systemback-ng.includes\n"
        "excludes = /etc/systemback-ng.excludes\n"
    )
    subprocess.run(
        ["tee", "/etc/systemback-ng.conf"],
        input=cfg_text,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _select_directory(title: str, text: str, initial: str) -> str | None:
    res = _zenity([
        "--file-selection",
        "--directory",
        "--title", title,
        "--text", text,
        "--filename", str(Path(initial).as_posix()) + "/",
    ])
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _run_with_progress(args: list[str], title: str, text: str) -> int:
    progress = subprocess.Popen(
        [
            "zenity",
            "--progress",
            "--title", title,
            "--text", text,
            "--percentage", "0",
            "--auto-close",
            "--no-cancel",
        ],
        stdin=subprocess.PIPE,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    try:
        cmd = ["stdbuf", "-oL", "-eL", BIN] + args
        logging.info("GUI run (progress): %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if not proc.stdout or not progress.stdin:
            return 1
        last_pct = 0
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                logging.info("CMD: %s", line)
            if line.startswith("SBPROGRESS "):
                try:
                    _, pct_str, msg = line.split(" ", 2)
                    pct = max(0, min(100, int(pct_str)))
                    if pct < last_pct:
                        pct = last_pct
                    last_pct = pct
                    progress.stdin.write(f"{pct}\n")
                    progress.stdin.write(f"#{msg}\n")
                    progress.stdin.flush()
                except Exception:
                    pass
            elif line:
                try:
                    progress.stdin.write(f"{last_pct}\n")
                    progress.stdin.write(f"#{line}\n")
                    progress.stdin.flush()
                except Exception:
                    pass
        rc = proc.wait()
        return rc
    finally:
        try:
            if progress.stdin:
                progress.stdin.close()
            progress.wait(timeout=2)
        except Exception:
            pass


def _run_pulsate(args: list[str], title: str, text: str) -> int:
    progress = subprocess.Popen(
        [
            "zenity",
            "--progress",
            "--title", title,
            "--text", text,
            "--pulsate",
            "--auto-close",
            "--no-cancel",
        ],
        stdin=subprocess.PIPE,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    try:
        cmd = ["stdbuf", "-oL", "-eL", BIN] + args
        logging.info("GUI run (pulsate): %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if not proc.stdout:
            return 1
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                logging.info("CMD: %s", line)
                try:
                    if progress.stdin:
                        progress.stdin.write(f"#{line}\n")
                        progress.stdin.flush()
                except Exception:
                    pass
        return proc.wait()
    finally:
        try:
            if progress.stdin:
                progress.stdin.close()
            progress.wait(timeout=2)
        except Exception:
            pass


def main() -> int:
    if os.geteuid() != 0:
        _error("This application must be run as root (sudo).")
        return 1
    cfg = load_config()
    setup_logging(cfg)
    logging.info("GUI started")

    while True:
        cfg = load_config()
        res = _zenity([
            "--list",
            "--title", "systemback-ng",
            "--text", "Select an action:",
            "--column", "Name",
            "--column", "Description",
            "--width", "900",
            "--height", "500",
            "Backup", "Create a new snapshot",
            "Restore", "Restore a snapshot to disk/partition",
            "Boot Fix", "Reinstall bootloader on a target disk",
            "Snapshot list", "View existing snapshots",
            "Settings", "Configure paths and defaults",
            "Erase current configuration", "Reset config and set snapshots dir to 'ToSet'",
            "Manage excludes", "Edit include/exclude lists",
            "Requirements Check", "Verify required system tools",
            "Exit", "Close the application",
        ])
        if res.returncode != 0:
            return 0
        choice = res.stdout.strip()
        if choice == "Exit":
            return 0

        if choice == "Backup":
            label = _zenity(["--entry", "--title", "Backup", "--text", "Snapshot label (optional):"]).stdout.strip()
            args = ["backup"]
            if label:
                args += ["--label", label]
            rc = _run_pulsate(args, "Backup", "Creating snapshot...")
            if rc == 0:
                _info("Backup completed.")
            else:
                _error("Backup failed.")

        elif choice == "Restore":
            if not _list_snapshots_root():
                _error(f"No snapshots found in {cfg.snapshots_dir}. Please run a backup first.")
                continue
            snap = _select_snapshot(cfg)
            if not snap:
                continue
            mode_res = _zenity([
                "--list",
                "--title", "Restore mode",
                "--text", "Select restore mode:",
                "--column", "Mode",
                "Disk (wipe and restore)",
                "Partition (restore into existing)",
            ])
            if mode_res.returncode != 0:
                continue
            mode = "disk" if "Disk" in mode_res.stdout else "partition"

            if mode == "disk":
                target = _select_disk()
                if not target:
                    target = _zenity(["--entry", "--title", "Target disk", "--text", "Disk (e.g. /dev/sdX):"]).stdout.strip()
            else:
                target = _zenity(["--entry", "--title", "Target partition", "--text", "Partition (e.g. /dev/sdX1):"]).stdout.strip()
            if not target:
                continue

            boot_res = _zenity([
                "--list",
                "--title", "Boot mode",
                "--text", "Select boot mode:",
                "--column", "Mode",
                "MBR (BIOS)",
                "UEFI",
            ])
            if boot_res.returncode != 0:
                continue
            boot = "mbr" if "MBR" in boot_res.stdout else "uefi"

            detected_fs = ""
            if mode == "partition":
                try:
                    detected_fs = os.popen(f"blkid -s TYPE -o value {target}").read().strip()
                except Exception:
                    detected_fs = ""
            default_fs = detected_fs if detected_fs in ("ext4", "xfs", "btrfs") else "ext4"
            fs_res = _zenity([
                "--list",
                "--radiolist",
                "--title", "Filesystem",
                "--text", "Select target filesystem:",
                "--column", "Pick",
                "--column", "Type",
                "TRUE" if default_fs == "ext4" else "FALSE", "ext4",
                "TRUE" if default_fs == "xfs" else "FALSE", "xfs",
                "TRUE" if default_fs == "btrfs" else "FALSE", "btrfs",
            ])
            if fs_res.returncode != 0:
                continue
            fs = fs_res.stdout.strip()
            if not fs:
                fs = default_fs

            swap_mib = 0
            esp_mib = 512
            efi_part = ""
            swap_part = ""
            if mode == "disk":
                swap_txt = _zenity(["--entry", "--title", "Swap size", "--text", "Swap size in GB (0 to disable):", "--entry-text", "0"]).stdout.strip()
                swap_mib = int(swap_txt) * 1024 if swap_txt.isdigit() else 0
                if boot == "uefi":
                    esp_txt = _zenity(["--entry", "--title", "ESP size", "--text", "EFI System Partition size in MiB:", "--entry-text", "512"]).stdout.strip()
                    esp_mib = int(esp_txt) if esp_txt.isdigit() else 512
            else:
                if boot == "uefi":
                    efi_part = _zenity(["--entry", "--title", "EFI partition", "--text", "EFI System Partition (e.g. /dev/sdX1):"]).stdout.strip()
                    if not efi_part:
                        continue
                swap_part = _zenity(["--entry", "--title", "Swap partition (optional)", "--text", "Swap partition (leave blank for none):"]).stdout.strip()

            args = [
                "restore",
                "--snapshot", snap,
                "--mode", mode,
                "--target", target,
                "--boot", boot,
                "--filesystem", fs,
                "--progress",
            ]
            if mode == "disk":
                args += ["--swap-mib", str(swap_mib)]
                if boot == "uefi":
                    args += ["--esp-mib", str(esp_mib)]
            else:
                if boot == "uefi":
                    args += ["--efi-part", efi_part]
                if swap_part:
                    args += ["--swap-part", swap_part]

            confirm = _zenity([
                "--question",
                "--title", "Confirm restore",
                "--text", f"This will ERASE all data on {target}. Continue?",
            ])
            if confirm.returncode != 0:
                continue
            rc = _run_pulsate(args, "Restore", "Restoring snapshot (this will erase target)...")
            if rc == 0:
                _info("Restore completed.")
            else:
                _error("Restore failed.")

        elif choice == "Boot Fix":
            target = _select_disk()
            if not target:
                target = _zenity(["--entry", "--title", "Target disk", "--text", "Disk (e.g. /dev/sdX):"]).stdout.strip()
            if not target:
                continue

            boot_res = _zenity([
                "--list",
                "--title", "Boot mode",
                "--text", "Select boot mode:",
                "--column", "Mode",
                "MBR (BIOS)",
                "UEFI",
            ])
            if boot_res.returncode != 0:
                continue
            boot = "mbr" if "MBR" in boot_res.stdout else "uefi"

            confirm = _zenity([
                "--question",
                "--title", "Confirm boot fix",
                "--text", f"This will reinstall the bootloader on {target}. Continue?",
            ])
            if confirm.returncode != 0:
                continue

            args = [
                "boot-fix",
                "--disk", target,
                "--boot", boot,
            ]
            rc = _run_pulsate(args, "Boot Fix", "Reinstalling bootloader...")
            if rc == 0:
                _info("Boot fix completed.")
            else:
                _error("Boot fix failed.")

        elif choice == "Snapshot list":
            snaps = _list_snapshots_root()
            if not snaps:
                _info("No snapshots.")
                continue
            rows = []
            for s in snaps:
                rows += [s["id"], s["label"] or "-", str(int(s["created"]))]
            _zenity([
                "--list",
                "--title", "Snapshots",
                "--text", "Existing snapshots:",
                "--column", "ID",
                "--column", "Label",
                "--column", "Created",
                "--height", "500",
            ] + rows)

        elif choice == "Settings":
            res = _zenity([
                "--list",
                "--title", "Settings",
                "--text", "Select a setting to change:",
                "--column", "Setting",
                "--column", "Current",
                "Snapshot directory", str(cfg.snapshots_dir),
                "Back",
            ])
            if res.returncode != 0:
                continue
            sub = res.stdout.strip()
            if sub == "Snapshot directory":
                snap_dir = _select_directory(
                    "Snapshots directory",
                    "Select snapshots storage directory:",
                    str(cfg.snapshots_dir),
                )
                if snap_dir:
                    _write_config_paths(snap_dir)
                _info("Snapshot directory updated.")

        elif choice == "Erase current configuration":
            confirm = _zenity([
                "--question",
                "--title", "Reset configuration",
                "--text", "This will reset configuration and set snapshots directory to 'ToSet'. Continue?",
            ])
            if confirm.returncode != 0:
                continue
            _write_config_paths("ToSet")
            _info("Configuration reset. Snapshots directory set to 'ToSet'.")

        elif choice == "Manage excludes":
            res = _zenity([
                "--list",
                "--title", "Excludes manager",
                "--text", "Select an action:",
                "--column", "Action",
                "--height", "400",
                "Edit excludes list",
                "Edit includes list",
                "Back",
            ])
            if res.returncode != 0:
                continue
            sub = res.stdout.strip()
            if sub == "Edit excludes list":
                _edit_file_with_root("/etc/systemback-ng.excludes", "Edit excludes")
            elif sub == "Edit includes list":
                _edit_file_with_root("/etc/systemback-ng.includes", "Edit includes")

        elif choice == "Requirements Check":
            rc = subprocess.call([BIN, "doctor"])
            if rc == 0:
                _info("Requirements: OK (see terminal for details).")
            else:
                _error("Requirements: issues detected (see terminal).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

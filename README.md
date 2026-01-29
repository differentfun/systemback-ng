# systemback-ng

**systemback-ng (New Generation)** is a minimal, robust rewrite of Systemback with a Python core and an optional Zenity GUI.

## Features
- CLI-first commands for backups, restore, diagnostics, and boot repair
- Optional Zenity GUI wrapper
- Snapshot verification with SHA256

## Project layout
- `bin/systemback-ng` – CLI entrypoint
- `bin/systemback-ng-gui` – GUI entrypoint
- `core/` – core logic
- `ui/` – Zenity GUI
- `systemd/` – unit/timer templates
- `config/` – config and include/exclude templates

## Requirements
Core tools typically required:
- `tar`, `zstd`, `sha256sum`
- `lsblk`, `parted`, `wipefs`, `partprobe`, `udevadm`, `blkid`
- `mkfs.ext4` (and optionally `mkfs.xfs`, `mkfs.btrfs`)
- `mkfs.vfat`, `mkswap`
- `grub-install`, `update-grub`

## Configuration
The CLI reads `/etc/systemback-ng.conf` (default template in `config/systemback-ng.conf`).

Important paths:
- `state_dir` – runtime state
- `snapshots_dir` – backup archives (`.tar.zst`)
- `includes` / `excludes` – include/exclude lists

Note: exclude rules are applied during backup; include rules are currently defined in config but not yet used by the backup engine.

## GUI usage
Run the GUI (requires root):
```bash
./launch.sh
```

The GUI provides Backup, Restore, Boot Fix, Snapshot list, and configuration shortcuts.

## Status
Working - Tested on Debian 13.

#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  if command -v pkexec >/dev/null 2>&1; then
    exec pkexec "$0" "$@"
  else
    echo "pkexec not found. Please run as root." >&2
    exit 1
  fi
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install -y \
  python3 \
  zenity \
  tar \
  zstd \
  coreutils \
  util-linux \
  parted \
  udev \
  e2fsprogs \
  dosfstools \
  xfsprogs \
  btrfs-progs \
  grub2-common \
  grub-common \
  grub-efi-amd64-bin \
  grub-pc-bin \
  polkitd \
  pkexec

cat <<'EOF'
Done.
- Required tools for backup/restore installed.
EOF

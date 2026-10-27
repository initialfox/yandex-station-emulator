#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[[ $(uname -s) == Linux ]] || { echo 'Linux required' >&2; exit 1; }
for program in python3 qemu-system-aarch64; do
    command -v "$program" >/dev/null || { echo "Install $program first (Debian: apt install python3 qemu-system-arm)" >&2; exit 1; }
done
python3 scripts/install_runtime.py
python3 qemu/mini2/tools/prepare_linux.py
echo 'Ready: bash qemu/mini2/start_linux.sh'

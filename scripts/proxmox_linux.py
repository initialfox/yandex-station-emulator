#!/usr/bin/env python3
"""Create a new Proxmox ARM VM from an already prepared Linux stand."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'qemu/mini2/tools'))
from prepare_linux import prepare
from start_linux import arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--name', default='yandex-mini2-linux')
    parser.add_argument('--adb-port', type=int, default=5556)
    parser.add_argument('--ssh-port', type=int, default=2223)
    parser.add_argument('--glagol-port', type=int, default=8444)
    opts = parser.parse_args()
    if not 100 <= opts.vmid <= 999999999:
        parser.error('Invalid Proxmox VM ID')
    ports = (opts.adb_port, opts.ssh_port, opts.glagol_port)
    if len(set(ports)) != 3 or any(not 1024 <= port <= 65535 for port in ports):
        parser.error('Choose three distinct unprivileged ports')
    # Never edit or replace an existing VM.
    if subprocess.run(['qm', 'config', str(opts.vmid)], capture_output=True).returncode == 0:
        raise SystemExit('VM ID already exists; choose an unused ID')
    prepare()
    extra = shlex.join(arguments(opts.adb_port, opts.glagol_port, ssh_port=opts.ssh_port))
    subprocess.run(['qm', 'create', str(opts.vmid), '--name', opts.name,
                    '--arch', 'aarch64', '--machine', 'virt', '--kvm', '0',
                    '--memory', '1024', '--cores', '4', '--balloon', '0',
                    '--vga', 'none', '--tablet', '0', '--ostype', 'l26',
                    '--onboot', '0', '--args', extra], check=True)
    print(f'Created VM {opts.vmid}. Start with: qm start {opts.vmid}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Linux ARM system emulation, with loopback-only management ports."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from prepare_linux import STAND, prepare


def arguments(adb_port=5556, glagol_port=8444, audio='none', ssh_port=2223, lan=False, bus_port=None):
    root = STAND / 'alpine_root-linux'
    run = STAND / 'run-linux'
    args = [
        '-kernel', str(STAND / 'alpine/vmlinuz-lts'),
        '-initrd', str(STAND / 'alpine/initramfs-9p.cpio.gz'),
        '-append', 'console=ttyAMA0 earlyprintk=serial root=/dev/root rw',
        '-fsdev', f'local,id=alpine,path={root},security_model=none',
        '-device', 'virtio-9p-pci,fsdev=alpine,mount_tag=alpine',
        '-fsdev', f'local,id=leds,path={STAND / "led_sysfs-linux"},security_model=none',
        '-device', 'virtio-9p-pci,fsdev=leds,mount_tag=leds',
        '-drive', f'file={STAND / "mini2-backup.ext4"},format=raw,if=none,id=firmware',
        '-device', 'virtio-blk-pci,drive=firmware',
        '-netdev', f'user,id=n0,hostfwd=tcp:127.0.0.1:{adb_port}-:5555,hostfwd=tcp:127.0.0.1:{glagol_port}-:443,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
        '-device', 'virtio-net-device,netdev=n0,mac=' + ('52:54:00:4d:32:02' if lan else '52:54:00:4d:32:01'),
        '-audiodev', f'{audio},id=audio',
        '-device', 'virtio-sound-pci,audiodev=audio',
    ]
    if bus_port is not None:
        pos = args.index('-netdev') + 1
        args[pos] += f',hostfwd=tcp:127.0.0.1:{bus_port}-:15558'
    nv = STAND.parents[1] / 'firmware/backups/yandex-mini2-backup/mtd/mtd4_nv.bin'
    if nv.is_file():
        args += ['-drive', f'file={nv},format=raw,if=none,id=nv,readonly=on', '-device', 'virtio-blk-pci,drive=nv']
    args += ['-chardev', f'socket,id=console,path={run / "console.sock"},server=on,wait=off,logfile={run / "console.log"}', '-serial', 'chardev:console']
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-proxmox-args', action='store_true', help='JSON array of extra arguments; caller supplies machine/CPU/RAM')
    parser.add_argument('--proxmox-lan', action='store_true', help='Private control NIC; caller must supply a bridged NIC with MAC 52:54:00:4d:32:01 and configure guest LAN mode')
    parser.add_argument('--adb-port', type=int, default=5556)
    parser.add_argument('--glagol-port', type=int, default=8444)
    parser.add_argument('--ssh-port', type=int, default=2223)
    parser.add_argument('--bus-port', type=int, help='Optional private D-Bus forward independent of ADB; requires guest dbus-control-forward')
    parser.add_argument('--audio', choices=('none', 'pa', 'alsa'), default='none')
    opts = parser.parse_args()
    if opts.proxmox_lan and not opts.print_proxmox_args:
        parser.error('--proxmox-lan requires --print-proxmox-args and an externally managed bridged NIC')
    ports = [opts.adb_port, opts.glagol_port, opts.ssh_port]
    if opts.bus_port is not None:
        ports.append(opts.bus_port)
    for port in ports:
        if not 1024 <= port <= 65535:
            parser.error('Use unprivileged TCP ports 1024–65535')
    if len(set(ports)) != len(ports):
        parser.error('Management ports must be different')
    if opts.print_proxmox_args:
        print(json.dumps(arguments(opts.adb_port, opts.glagol_port, opts.audio, opts.ssh_port, opts.proxmox_lan, opts.bus_port)))
        return
    qemu = shutil.which(os.environ.get('QEMU', 'qemu-system-aarch64'))
    if not qemu:
        raise SystemExit('Install qemu-system-aarch64')
    # flock prevents two Linux launches from opening the same writable disk.
    import fcntl
    (STAND / 'run-linux').mkdir(exist_ok=True)
    with (STAND / 'run-linux/launch.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Linux stand is already running')
        prepare()
        command = [qemu, '-M', 'virt', '-accel', 'tcg', '-cpu', 'cortex-a53', '-smp', '4', '-m', '1024', '-display', 'none', '-monitor', 'none']
        result = subprocess.run(command + arguments(opts.adb_port, opts.glagol_port, opts.audio, opts.ssh_port, bus_port=opts.bus_port))
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

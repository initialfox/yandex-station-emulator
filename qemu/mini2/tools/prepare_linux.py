#!/usr/bin/env python3
"""Prepare a separate Linux bootstrap; never recreate the firmware disk."""
import os
from pathlib import Path
import shutil
import time

STAND = Path(__file__).resolve().parents[1]


def prepare():
    source = STAND / 'alpine_root'
    root = STAND / 'alpine_root-linux'
    if not (source / 'bin').is_dir():
        raise SystemExit('Run scripts/install_runtime.py first')
    if not root.exists():
        shutil.copytree(source, root, symlinks=True)
    run = STAND / 'run-linux'
    run.mkdir(mode=0o700, exist_ok=True)
    (root / 'opt/mini2/host_epoch').write_text(str(int(time.time())))
    mode = root / 'opt/mini2/network_mode'
    if not mode.exists():
        mode.write_text('nat\n')
    keys = Path(os.environ.get('PEM_SOURCE_DIR', str(STAND.parents[1] / 'keys')))
    staged = root / 'opt/mini2/pem-keys'
    staged.mkdir(mode=0o700, exist_ok=True)
    for name in ('private.pem', 'public.pem'):
        shutil.copyfile(keys / name, staged / name)
        (staged / name).chmod(0o600)
    # No macOS microphone service on Linux. Supply silence in headless mode.
    # A real capture bridge must explicitly replace this source.
    script = (STAND / 'guest/mini2.start').read_text()
    # QEMU initializes the RTC on every start; a staged epoch would grow stale.
    script = script.replace('if [ -f /opt/mini2/host_epoch ]; then\n    date -u -s "@$(cat /opt/mini2/host_epoch)"\nfi', ': # Use the QEMU RTC')
    # A Proxmox restart does not run the interactive launcher. Retain the
    # explicitly selected key pair in the mode-0700 local bootstrap directory.
    script = script.replace('rm -f /opt/mini2/pem-keys/private.pem /opt/mini2/pem-keys/public.pem', ': # Retain keys for the next Linux VM boot')
    script = script.replace('if [ -f /opt/mini2/mic_relay ]; then', 'if false; then')
    marker = 'chroot /mini2 /bin/sh /emulator/alice-start.sh'
    extra = '''
mkfifo /mini2/tmp/mac-microphone.pcm
dd if=/dev/zero of=/mini2/tmp/mac-microphone.pcm bs=4096 >/tmp/silent-mic.log 2>&1 &
# A separate shell does not inherit this bootstrap's errexit setting.
/bin/sh /opt/mini2/adb-linux-watch.sh &
echo $! >/run/mini2-adb-watch.pid
if [ -x /opt/mini2/dbus-control-forward ]; then
    /bin/sh /opt/mini2/dbus-control-watch.sh >/tmp/dbus-control-forward.log 2>&1 &
fi
if [ "$(cat /opt/mini2/network_mode)" = lan ] && [ -x /opt/mini2/wpa-lan-proxy ]; then
    sed -i 's@ctrl_interface=/var/run/wpa_supplicant@ctrl_interface=/var/run/wpa-lan-backend@' /mini2/emulator/wpa-wired.conf
    /bin/sh /opt/mini2/wpa-lan-watch.sh >/tmp/wpa-lan-proxy.log 2>&1 &
    echo $! >/run/mini2-wpa-watch.pid
fi
'''
    script = script.replace(marker, extra + '\n' + marker)
    target = root / 'etc/local.d/mini2.start'
    target.write_text(script)
    target.chmod(0o755)
    watcher = root / 'opt/mini2/adb-linux-watch.sh'
    shutil.copyfile(STAND / 'guest/adb-linux-watch.sh', watcher)
    watcher.chmod(0o755)
    shutil.copyfile(STAND / 'guest/wpa-lan-watch.sh', root / 'opt/mini2/wpa-lan-watch.sh')
    shutil.copyfile(STAND / 'guest/dbus-control-watch.sh', root / 'opt/mini2/dbus-control-watch.sh')
    bus_binary = os.environ.get('LINUX_DBUS_FORWARD_BINARY')
    if bus_binary:
        shutil.copyfile(bus_binary, root / 'opt/mini2/dbus-control-forward')
        (root / 'opt/mini2/dbus-control-forward').chmod(0o755)
    proxy_binary = os.environ.get('LINUX_LAN_PROXY_BINARY')
    if proxy_binary:
        shutil.copyfile(proxy_binary, root / 'opt/mini2/wpa-lan-proxy')
        (root / 'opt/mini2/wpa-lan-proxy').chmod(0o755)
    pem_binary = os.environ.get('LINUX_PEM_PROXY_BINARY')
    if pem_binary:
        shutil.copyfile(pem_binary, root / 'opt/mini2/pem_proxy')
        (root / 'opt/mini2/pem_proxy').chmod(0o755)
    # Optional SSH uses a user-supplied static ARM binary and public key only.
    binary = os.environ.get('LINUX_DROPBEAR_BINARY')
    public_key = os.environ.get('LINUX_AUTHORIZED_KEYS')
    if bool(binary) != bool(public_key):
        raise SystemExit('Set both LINUX_DROPBEAR_BINARY and LINUX_AUTHORIZED_KEYS for SSH')
    if binary:
        shutil.copyfile(binary, root / 'opt/mini2/dropbear-linux')
        (root / 'opt/mini2/dropbear-linux').chmod(0o755)
        shutil.copyfile(public_key, root / 'opt/mini2/authorized_keys-linux')
    if (root / 'opt/mini2/dropbear-linux').is_file():
        script += '''
mkdir -p /mini2/bkupgrade/data/local/owner-ssh /mini2/root/.ssh /mini2/etc/dropbear
chmod 700 /mini2/root/.ssh
cp /opt/mini2/authorized_keys-linux /mini2/root/.ssh/authorized_keys
chmod 600 /mini2/root/.ssh/authorized_keys
cp /opt/mini2/dropbear-linux /mini2/bkupgrade/data/local/owner-ssh/dropbear
chmod 755 /mini2/bkupgrade/data/local/owner-ssh/dropbear
chroot /mini2 /data/local/owner-ssh/dropbear -R -s -j -k -p 22 -P /tmp/owner-dropbear.pid
'''
        target.write_text(script)
    script += '''
# Optional, data-only YAM bootstrap. Do not follow /mini2/data outside chroot.
touch /mini2/emulator/yam-autostart-supported
if [ -f /mini2/bkupgrade/data/local/yam/autostart ] && [ -x /mini2/bkupgrade/data/local/yam/start.sh ]; then
    chroot /mini2 /data/local/yam/start.sh >/mini2/tmp/yam-autostart.log 2>&1 || true
fi
'''
    target.write_text(script)
    leds = STAND / 'led_sysfs-linux'
    if not leds.exists():
        import subprocess
        import sys
        subprocess.run([sys.executable, str(STAND / 'tools/mk_led_sysfs.py'), '--out', str(leds)], check=True)
    return root


if __name__ == '__main__':
    print(prepare())

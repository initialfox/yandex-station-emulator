"""Mini 2 YAM installation, isolated from the Light 2 persistence hook."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.request

BASE = '/data/local/yam'
START = '''#!/bin/sh
set -eu
D=/data/local/yam
test -x "$D/bin/yamd"
pidof yamd >/dev/null 2>&1 && exit 0
start-stop-daemon -S -b -m -p /tmp/mini2-yamd.pid -x /bin/sh -- -c 'exec /data/local/yam/bin/yamd --listen 127.0.0.1:8099 --data-dir /data/local/yam/data --model yandexmini_2 >>/data/local/yam/yamd.log 2>&1'
'''
INIT = '''#!/bin/sh
# mini2-webpanel-yam: optional native Mini 2 SysV startup, not the Light 2 hook.
case "${1:-start}" in
 start) [ ! -f /data/local/yam/autostart ] || /data/local/yam/start.sh ;;
esac
'''
SETTINGS = '''allow_plugin_binaries = false
[led]
profile = "mini2"
count = 6
sysfs_root = "/sys/class/leds"
[web]
ui = true
api = true
[updates]
enabled = false
interval_minutes = 360
'''


def install(s):
    lock = threading.RLock()
    original_action = s.Panel.yam_action if hasattr(s.Panel, 'yam_action') else None

    def upload(self, data, remote):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_bytes(data.encode() if isinstance(data, str) else data)
            self.adb.push(path, remote)

    def status(self):
        out = self.adb.shell(
            f'[ -x {BASE}/bin/yamd ] && echo installed; '
            'pidof yamd >/dev/null && echo running; '
            "awk '$4==\"0A\" && $2 ~ /:1FA3$/ {print \"listening\"}' /proc/net/tcp /proc/net/tcp6; "
            f'[ -f {BASE}/autostart ] && echo autostart; true')[0].split()
        # The guest API is loopback-only; do not offer the mini-PC's unrelated :8099.
        return dict(installed='installed' in out, running='running' in out and 'listening' in out,
                    autostart='autostart' in out, web_url=None)

    def start(self):
        with lock:
            self.adb.shell(f'{BASE}/start.sh', timeout=30)
            for _ in range(20):
                if self.yam_status()['running']:
                    self._yam('GET', '/api/device')
                    return self.yam_status()
                time.sleep(.5)
            raise s.AdbError('YAM не запустился: ' + self.adb.shell(f'tail -5 {BASE}/yamd.log', check=False)[0][-400:])

    def install_daemon(self):
        with lock:
            arch = self.adb.shell('uname -m')[0].strip()
            if arch not in ('aarch64', 'arm64'):
                raise s.AdbError('Для ядра ' + arch + ' нет официального yamd: нужен совместимый ARM32-релиз')
            url = 'https://api.github.com/repos/nyakokitsu/yam/releases/latest'
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'webpanel'}), timeout=20) as response:
                release = json.load(response)
            asset = 'yamd-aarch64-linux-musl'
            assets = {item['name']: item['browser_download_url'] for item in release['assets']}
            if asset not in assets or 'SHA256SUMS' not in assets:
                raise s.AdbError('В релизе нет совместимого yamd и контрольных сумм')
            with urllib.request.urlopen(assets['SHA256SUMS'], timeout=30) as response:
                sums = response.read().decode().splitlines()
            expected = next((line.split()[0] for line in sums if line.split()[-1:] == [asset]), None)
            with urllib.request.urlopen(assets[asset], timeout=120) as response:
                blob = response.read()
            if hashlib.sha256(blob).hexdigest() != expected:
                raise s.AdbError('Контрольная сумма yamd не совпала')
            self.adb.shell(f'mkdir -p {BASE}/bin {BASE}/data; chmod 700 {BASE} {BASE}/data')
            upload(self, blob, BASE + '/bin/yamd.new')
            # Execute the candidate before replacing anything on 32-bit userspace.
            self.adb.shell(f'chmod 755 {BASE}/bin/yamd.new; {BASE}/bin/yamd.new --help', timeout=30)
            stamp = time.strftime('%Y%m%dT%H%M%S')
            self.adb.shell(f'[ ! -f {BASE}/bin/yamd ] || cp -p {BASE}/bin/yamd {BASE}/bin/yamd.before-{stamp}; '
                           f'[ ! -f {BASE}/data/settings.toml ] || cp -p {BASE}/data/settings.toml {BASE}/settings.before-{stamp}; true')
            upload(self, START, BASE + '/start.sh.new')
            upload(self, SETTINGS, BASE + '/data/settings.initial')
            self.adb.shell(f'chmod 700 {BASE}/start.sh.new; mv {BASE}/start.sh.new {BASE}/start.sh; '
                           f'[ -f {BASE}/data/settings.toml ] || cp {BASE}/data/settings.initial {BASE}/data/settings.toml; '
                           f'pidof yamd >/dev/null && kill $(pidof yamd); sleep 1; mv {BASE}/bin/yamd.new {BASE}/bin/yamd')
            try:
                return {**self.yam_start(), 'version': release['tag_name']}
            except Exception:
                self.adb.shell(f'pidof yamd >/dev/null && kill $(pidof yamd); '
                               f'if [ -f {BASE}/bin/yamd.before-{stamp} ]; then '
                               f'cp -p {BASE}/bin/yamd.before-{stamp} {BASE}/bin/yamd; {BASE}/start.sh; fi; true', check=False)
                raise

    def autostart(self, enabled):
        with lock:
            if enabled:
                if not self.yam_status()['installed']:
                    raise s.AdbError('Сначала установите YAM')
                # Linux VM explicitly advertises its bootstrap hook. Real Mini 2
                # uses its own verified writable SysV init directory instead.
                vm = self.adb.shell('test -f /emulator/yam-autostart-supported && echo vm; true')[0].strip() == 'vm'
                if not vm:
                    out = self.adb.shell("test -w /etc/init.d && grep -q '/etc/init.d/S' /etc/init.d/rcS && echo native; true")[0]
                    if 'native' not in out:
                        raise s.AdbError('Автозапуск этой прошивки не проверен; ручной запуск YAM доступен')
                    current = self.adb.shell('cat /etc/init.d/S98yam 2>/dev/null; true')[0]
                    if current and 'mini2-webpanel-yam' not in current:
                        raise s.AdbError('Существующий S98yam не принадлежит панели; он сохранён')
                    upload(self, INIT, BASE + '/init.new')
                    self.adb.shell(f'cp {BASE}/init.new /etc/init.d/S98yam; chmod 755 /etc/init.d/S98yam')
                self.adb.shell(f'touch {BASE}/autostart')
            else:
                self.adb.shell(f'rm -f {BASE}/autostart')
            return self.yam_status()

    def action(self, operation, identifier):
        # YAM 0.1.17+ separates service lifecycle from oneshot invocation.
        if operation in ('run', 'stop', 'toggle'):
            packages = self.yam_plugins()
            package = next((item for item in packages if item['manifest']['id'] == identifier), None)
            if package and package['manifest'].get('launch', {}).get('mode') == 'service':
                path = '/api/plugins/' + identifier
                if operation == 'toggle':
                    self._yam('POST', path + '/service/' + ('disable' if package['enabled'] else 'enable'))
                    if package['enabled']:
                        return original_action(self, operation, identifier)
                else:
                    self._yam('POST', path + ('/service/start' if operation == 'run' else '/stop'))
                return {'ok': True}
        return original_action(self, operation, identifier)

    s.Panel.yam_status = status
    s.Panel.yam_start = start
    s.Panel.yam_install_daemon = install_daemon
    s.Panel.yam_autostart = autostart
    s.Panel.yam_action = action
    s.Panel.YAM_ASSET = 'yamd-aarch64-linux-musl'
    s.Panel._yam_sums = {}

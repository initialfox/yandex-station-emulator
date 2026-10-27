import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import os
import signal
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'qemu/mini2/tools'))
sys.path.insert(0, str(REPO / 'integrations/yandex_station_web'))
from start_linux import arguments


class LinuxRegression(unittest.TestCase):
    def test_mini2_shell_requests_are_serialized(self):
        spec = importlib.util.spec_from_file_location('mini2_serial_profile', REPO / 'integrations/yandex_station_web/mini2_profile.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Adb:
            def __init__(self):
                self.lock = threading.Lock()
                self.active = self.maximum = 0

            def shell(self, command, timeout=15, check=True):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                time.sleep(.01)
                self.active -= 1
                return 'ok', '', 0

        server = types.SimpleNamespace(Adb=Adb, Panel=type('Panel', (), {}))
        namespace = {'PROFILES': {}, 'install': lambda *args: None}
        module.register(namespace)
        namespace['install'](server, 'mini2')
        adb = Adb()
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(lambda _: adb.shell('echo ok'), range(10)))
        self.assertTrue(all(response[0] == 'ok' for response in responses))
        self.assertEqual(adb.maximum, 1)

    @unittest.skipIf(sys.platform == 'win32', 'needs a POSIX shell')
    def test_adb_watcher_retries_after_child_segfault_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'tmp').mkdir()
            bindir = root / 'bin'
            bindir.mkdir()
            pidof = bindir / 'pidof'
            pidof.write_text('#!/bin/sh\nexit 1\n')
            pidof.chmod(0o755)
            chroot = bindir / 'fake-chroot'
            chroot.write_text('#!/bin/sh\nif [ ! -e "$COUNT" ]; then echo 1 >"$COUNT"; exit 139; fi\necho 2 >"$COUNT"\nsleep 30\n')
            chroot.chmod(0o755)
            count = root / 'count'
            environment = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                               MINI2_ADB_ROOT=str(root), MINI2_ADB_CHROOT=str(chroot),
                               MINI2_ADB_RETRY_SECONDS='0.05', COUNT=str(count))
            watcher = subprocess.Popen(['sh', str(REPO / 'qemu/mini2/guest/adb-linux-watch.sh')], env=environment, start_new_session=True)
            try:
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    if count.exists() and count.read_text().strip() == '2':
                        break
                    time.sleep(0.02)
                self.assertIsNone(watcher.poll())
                self.assertEqual(count.read_text().strip(), '2')
                self.assertIn('rc=139', (root / 'tmp/adbd.log').read_text())
            finally:
                os.killpg(watcher.pid, signal.SIGTERM)
                watcher.wait(timeout=3)

    def test_management_forwarding_is_loopback_only(self):
        args = arguments()
        net = args[args.index('-netdev') + 1]
        self.assertEqual(net.count('hostfwd=tcp:127.0.0.1:'), 3)
        self.assertNotIn('coreaudio', ' '.join(args))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nv = root / 'firmware/backups/yandex-mini2-backup/mtd/mtd4_nv.bin'
            nv.parent.mkdir(parents=True)
            nv.write_bytes(b'test-only')
            with patch('start_linux.STAND', root / 'qemu/mini2'):
                self.assertIn('readonly=on', ' '.join(arguments()))

    @unittest.skipIf(sys.platform == 'win32', 'needs a POSIX shell')
    def test_emulated_led_reads_without_newlines_or_during_truncation(self):
        spec = importlib.util.spec_from_file_location('mini2_profile', REPO / 'integrations/yandex_station_web/mini2_profile.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = types.SimpleNamespace(Panel=type('Panel', (), {}), CLOCK_LEDS=list(range(36)), AdbError=RuntimeError,
                                       Adb=type('BaseAdb', (), {'shell': lambda *args, **kwargs: None}))
        ns = {'PROFILES': {}, 'install': lambda *args: None}
        module.register(ns)
        ns['install'](server, 'mini2')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for digit in range(1, 5):
                for segment in 'ABCDEFG':
                    path = root / f'mini2:white:clock{segment}{digit}'
                    path.mkdir()
                    (path / 'brightness').write_text('7')
            for index in range(1, 7):
                for color in ('red', 'green', 'blue'):
                    path = root / f'mini2:{color}:ring{index}'
                    path.mkdir()
                    (path / 'brightness').write_text('' if (index, color) == (2, 'green') else '123')

            class Adb:
                calls = 0

                def shell(self, command):
                    self.calls += 1
                    # Old adbd truncates commands longer than its small payload.
                    self_length = len(command.encode())
                    if self_length > 3500:
                        raise RuntimeError('command too long for old adbd')
                    result = subprocess.run(['sh', '-c', command.replace('/sys/class/leds', str(root))], capture_output=True, text=True, check=True)
                    return result.stdout, result.stderr, result.returncode

            panel = server.Panel()
            panel.adb = Adb()
            result = panel.clock_state()
            self.assertEqual(result['ring_all'][1], [123, 0, 123])
            self.assertEqual(result['ring_all'][2], [123, 123, 123])
            self.assertEqual(result['v'][:8], [7]*7 + [0])
            self.assertEqual(len(result['v']), 36)
            self.assertEqual(server.LedStream(panel.adb).get(), result)
            self.assertEqual(panel.adb.calls, 1, 'clock and stream must share their cached snapshot')


if __name__ == '__main__':
    unittest.main()

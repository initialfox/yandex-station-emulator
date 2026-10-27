import importlib.util
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_scan_linux', ROOT / 'qemu/mini2/tools/wifi_scan_linux.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class ScanTests(unittest.TestCase):
    def test_real_scan_fields_and_hidden_network(self):
        text = '''BSS 02:00:00:00:00:01(on wlan9)
    freq: 5180
    signal: -47.50 dBm
    SSID: Example network
\tRSN:
        Authentication suites: PSK
BSS 02:00:00:00:00:02(on wlan9)
    freq: 2412
    signal: -80.00 dBm
    SSID:
'''
        result = scan.scan_rows(text)
        self.assertIn('5180\t-47\t[WPA2-PSK-CCMP][ESS]\tExample network', result)
        self.assertEqual(len(result.splitlines()), 2)

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX') and shutil.which('gcc'), 'POSIX C compiler required')
    def test_unix_control_events_and_password_discard(self):
        with tempfile.TemporaryDirectory(prefix='wpa-test-') as tmp:
            d = Path(tmp)
            binary = d / 'proxy'
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-O2',
                            str(ROOT / 'qemu/mini2/guest/wpa-lan-proxy.c'), '-o', str(binary)], check=True)
            back = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            back.bind(str(d / 'backend'))
            seen = []
            stop = threading.Event()

            def backend():
                back.settimeout(.1)
                while not stop.is_set():
                    try:
                        data, addr = back.recvfrom(65536)
                    except socket.timeout:
                        continue
                    seen.append(data)
                    back.sendto(b'OK\n', addr)

            thread = threading.Thread(target=backend)
            thread.start()
            rows = b'bssid / frequency / signal level / flags / ssid\n02:00:00:00:00:01\t2412\t-40\t[ESS]\tExample\n'
            (d / 'scan').write_bytes(rows)
            proc = subprocess.Popen([str(binary), str(d / 'front'), str(d / 'backend'), str(d / 'scan')], stderr=subprocess.PIPE)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            client.bind(str(d / 'client'))
            client.settimeout(2)
            try:
                for _ in range(100):
                    if (d / 'front').exists():
                        break
                    time.sleep(.01)
                client.connect(str(d / 'front'))
                def call(cmd):
                    client.send(cmd)
                    return client.recv(65536)
                self.assertEqual(call(b'ATTACH'), b'OK\n')
                self.assertEqual(call(b'SCAN'), b'OK\n')
                self.assertIn(b'CTRL-EVENT-SCAN-RESULTS', client.recv(1024))
                self.assertEqual(call(b'SCAN_RESULTS'), rows)
                self.assertEqual(call(b'SET_NETWORK 4 psk "test-only-password"'), b'OK\n')
                self.assertEqual(call(b'SET_NETWORK 4 key_mgmt WPA-PSK'), b'OK\n')
                self.assertIn(b'SET_NETWORK 4 key_mgmt NONE', seen)
                self.assertFalse(any(b'password' in x or b'psk' in x for x in seen))
            finally:
                proc.terminate()
                _, log = proc.communicate(timeout=2)
                stop.set()
                thread.join(2)
                client.close()
                back.close()
            self.assertNotIn(b'test-only-password', log)


if __name__ == '__main__':
    unittest.main()

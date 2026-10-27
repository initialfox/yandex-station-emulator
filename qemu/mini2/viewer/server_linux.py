#!/usr/bin/env python3
"""Loopback Linux viewer; optionally delegate lifecycle to Proxmox qm."""
import argparse
import os
import signal
from pathlib import Path
import subprocess
import sys

import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8870)
    parser.add_argument('--proxmox-vmid', type=int)
    options = parser.parse_args()
    if not 1024 <= options.port <= 65535:
        parser.error('Use a port between 1024 and 65535')
    if options.proxmox_vmid is not None and options.proxmox_vmid < 100:
        parser.error('Invalid VM ID')
    server.PORT = options.port
    server.RUN = server.STAND / 'run-linux'
    server.LED_SYSFS = server.STAND / 'led_sysfs-linux'
    server.START_SH = server.STAND / 'start_linux.sh'
    server.RUN.mkdir(exist_ok=True)
    server.start_alice_leds = lambda mode: {'ok': False, 'error': 'Synthetic host LED demo is disabled on Linux; firmware drives the LEDs.'}
    # Never terminate a process based on a command-line substring.
    child = None

    def start():
        nonlocal child
        if server.qemu_status()['up']:
            return server.qemu_status()
        if options.proxmox_vmid:
            subprocess.run(['qm', 'start', str(options.proxmox_vmid)], check=True)
        else:
            log = (server.RUN / 'start.log').open('ab')
            try:
                child = subprocess.Popen(['bash', str(server.START_SH)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                log.close()
        return server.qemu_status()

    def stop():
        nonlocal child
        # Give the guest a chance to flush and power down before stopping it.
        sock = server.RUN / 'console.sock'
        if sock.exists():
            subprocess.run([sys.executable, str(server.STAND / 'tools/console.py'),
                            'sync; poweroff', '--socket', str(sock), '--timeout', '3'],
                           capture_output=True, timeout=10)
        if options.proxmox_vmid:
            subprocess.run(['qm', 'stop', str(options.proxmox_vmid)], check=True)
        elif child is not None:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=15)
            child = None
        return server.qemu_status()

    server.start_qemu = start
    server.stop_qemu = stop
    original = server.Handler

    class Handler(original):
        def _cors(self):
            # No wildcard CORS on this local management interface.
            self.send_header('X-Content-Type-Options', 'nosniff')

        def do_POST(self):
            host = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{options.port}', f'localhost:{options.port}'}
            origin = self.headers.get('Origin')
            if host not in allowed or (origin is not None and origin not in {'http://' + item for item in allowed}):
                return self._json({'error': 'Origin rejected'}, code=403)
            if self.headers.get_content_type() != 'application/json':
                return self._json({'error': 'application/json required'}, code=415)
            return super().do_POST()

    server.Handler = Handler
    server.ensure_led_bridge = lambda: None
    env = dict(os.environ, ALICE_VIEWER_URL=f'http://127.0.0.1:{options.port}/api/event')
    helpers = [subprocess.Popen([sys.executable, str(server.ROOT / 'led_bridge.py'), str(server.LED_SYSFS)], env=env),
               subprocess.Popen([sys.executable, str(server.ROOT / 'console_tail.py'), str(server.RUN / 'console.log')], env=env)]
    try:
        server.main()
    finally:
        for helper in helpers:
            helper.terminate()
        for helper in helpers:
            helper.wait(timeout=5)
        # A standalone VM remains alive when its viewer closes. Use Stop first.


if __name__ == '__main__':
    main()

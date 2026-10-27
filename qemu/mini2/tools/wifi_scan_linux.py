#!/usr/bin/env python3
"""Cache real host radio scan results for the VM's LAN onboarding adapter."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import time


def scan_rows(text):
    rows = []
    for block in re.split(r'(?m)^BSS ', text)[1:]:
        mac = block.split('(', 1)[0].strip()
        freq = re.search(r'(?m)^\s*freq: (\d+)', block)
        signal = re.search(r'(?m)^\s*signal: (-?[\d.]+)', block)
        ssid = re.search(r'(?m)^\s*SSID: (.*)$', block)
        if not (re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac) and freq and signal and ssid):
            continue
        name = ssid[1].replace('\t', '\\t').replace('\r', '\\r')
        if not name:
            continue
        flags = '[WPA2-PSK-CCMP][ESS]' if '\n\tRSN:' in block else '[ESS]'
        if 'Authentication suites: SAE' in block:
            flags = '[WPA2-SAE-CCMP][ESS]'
        rows.append(f'{mac}\t{freq[1]}\t{int(float(signal[1]))}\t{flags}\t{name}\n')
    return 'bssid / frequency / signal level / flags / ssid\n' + ''.join(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--interface', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    while True:
        try:
            r = subprocess.run(['iw', 'dev', args.interface, 'scan'],
                               capture_output=True, text=True, timeout=20, check=True)
            data = scan_rows(r.stdout)
            tmp = args.output.with_suffix('.new')
            tmp.write_text(data)
            tmp.replace(args.output)
            print(f'Updated Wi-Fi scan: {len(data.splitlines()) - 1} APs', flush=True)
        except (OSError, subprocess.SubprocessError):
            print('Host Wi-Fi scan unavailable; retaining previous results', flush=True)
        time.sleep(20)


if __name__ == '__main__':
    main()

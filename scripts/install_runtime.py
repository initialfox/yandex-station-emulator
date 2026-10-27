#!/usr/bin/env python3
"""Verify and unpack the included runtime parts; never replace an existing VM."""
import argparse
import hashlib
import io
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

repo=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,default=repo);a=p.parse_args()
target=a.destination.resolve();target.mkdir(parents=True,exist_ok=True)
manifest=json.loads((repo/'assets/runtime-manifest.json').read_text())
paths=[];total=hashlib.sha256()
for part in manifest['parts']:
    path=repo/'assets'/part['file'];digest=hashlib.sha256();size=0
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block);total.update(block);size+=len(block)
    if size!=part['size'] or digest.hexdigest()!=part['sha256']:raise SystemExit(f'Checksum mismatch: {path.name}')
    paths.append(path)
if total.hexdigest()!=manifest['archive_sha256']:raise SystemExit('Archive checksum mismatch')
disk=target/'qemu/mini2/mini2-backup.ext4'
if disk.exists():
    print('Runtime verified; existing guest disk preserved.');raise SystemExit(0)
class Parts(io.RawIOBase):
    def __init__(self,paths):self.paths=iter(paths);self.current=None
    def readable(self):return True
    def readinto(self,buffer):
        while True:
            if self.current is None:
                try:self.current=next(self.paths).open('rb')
                except StopIteration:return 0
            n=self.current.readinto(buffer)
            if n:return n
            self.current.close();self.current=None
    def close(self):
        if self.current:self.current.close()
        super().close()
with io.BufferedReader(Parts(paths)) as stream:
    with tarfile.open(fileobj=stream,mode='r|gz') as archive:
        for member in archive:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] not in ('qemu','firmware'):raise SystemExit('Unsafe archive path')
            # Absolute symlinks are intentional inside the chroot bootstrap.
            options = {'filter': 'fully_trusted'} if 'filter' in inspect.signature(archive.extract).parameters else {}
            archive.extract(member, target, **options)
(target/'qemu/mini2/run').mkdir(exist_ok=True)
(target/'qemu/mini2/led_sysfs').mkdir(exist_ok=True)
print('Runtime installed:',disk)

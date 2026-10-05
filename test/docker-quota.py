#!/usr/bin/env python3
"""Synthetic kernel-fact tests; these do not establish a real loop mount."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import copy
import importlib.util
import os
import stat
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
data, image = provider.DATA, provider.CONTROL / 'storage.ext4'
valid = dict(mounted=True, device=os.makedev(7, 0), image_device=os.makedev(8, 0),
             backing=str(image), uid=0, mode=stat.S_IFREG | 0o600,
             size=provider.BUILD_BYTES, links=1, directory_mode=stat.S_IFDIR | 0o755,
             blocks=provider.BUILD_BYTES // 4096, fragment=4096, available=1024*1024)


def inspect(facts):
    def metadata(path):
        directory = path != image
        return SimpleNamespace(st_mode=facts['directory_mode'] if directory else facts['mode'],
                               st_uid=facts['uid'], st_size=facts['size'], st_nlink=facts['links'])
    def device(path):
        return SimpleNamespace(st_dev=facts['device'] if path == data else facts['image_device'])
    def backing(path):
        assert str(path) == '/sys/dev/block/7:0/loop/backing_file'
        return facts['backing'] + '\n'
    fs = SimpleNamespace(f_blocks=facts['blocks'], f_frsize=facts['fragment'], f_bavail=facts['available'])
    with patch.object(provider.os, 'lstat', side_effect=metadata), \
         patch.object(provider.os, 'stat', side_effect=device), \
         patch.object(provider.os.path, 'ismount', return_value=facts['mounted']), \
         patch.object(provider.os, 'statvfs', return_value=fs), \
         patch.object(provider.Path, 'read_text', backing):
        return provider.quota_filesystem(data, image)


result = inspect(valid)
assert result['capacity_bytes'] == provider.BUILD_BYTES
print('PASS quota identity accepts consistent synthetic kernel facts', flush=True)
cases = [
    ('missing mount', 'mounted', False),
    ('unowned path', 'uid', 1000),
    ('writable image', 'mode', stat.S_IFREG | 0o666),
    ('symlink image', 'mode', stat.S_IFLNK | 0o777),
    ('writable directory', 'directory_mode', stat.S_IFDIR | 0o777),
    ('symlink directory', 'directory_mode', stat.S_IFLNK | 0o777),
    ('wrong size', 'size', provider.BUILD_BYTES + 4096),
    ('hardlinked image', 'links', 2),
    ('shared device', 'image_device', valid['device']),
    ('wrong backing file', 'backing', '/tmp/unrelated.ext4'),
    ('oversized filesystem', 'blocks', valid['blocks'] + 1),
    ('invalid geometry', 'fragment', 0),
    ('empty filesystem', 'blocks', 0),
    ('exhausted reserve', 'available', 1),
]
for label, key, value in cases:
    facts = copy.copy(valid)
    facts[key] = value
    try:
        inspect(facts)
    except RuntimeError:
        print('PASS quota identity refuses ' + label, flush=True)
    else:
        raise AssertionError('accepted ' + label)
print(f'Bootstrap quota: {len(cases) + 1} synthetic cases passed', flush=True)
